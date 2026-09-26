"""Turns queued trials into attempts (Kubernetes Jobs) and settles attempts whose pods ended silently.

Guarantees, each covered by a failure-injection test in tests/test_dispatcher.py:
- A trial accepted by the API is never lost: ids sit in Redis (queue or processing list) until the
  trial has a launched attempt, and recover() re-queues whatever a crashed dispatcher held.
- Dispatch is idempotent: a trial with an active attempt is never given a second one, and relaunching
  an attempt reuses its Job name, so duplicate queue delivery can't double-execute.
- A pod that ends without reporting is settled by reconcile():
    deadline exceeded             -> attempt timed_out, trial errored (agent failure, not retried)
    crashed / vanished / no report -> attempt infra_failed; retried up to max_infra_retries, then the
                                      trial is infra_failed (excluded from metrics, reported separately)
"""

import logging
import time
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ATTEMPT_ACTIVE, TRIAL_TERMINAL, Attempt, Trial, utcnow
from app.queue import RedisTrialQueue, TrialQueue
from app.settings import Settings, settings

log = logging.getLogger("dispatcher")


class Dispatcher:
    def __init__(self, sessions: Callable[[], Session], queue: TrialQueue, launcher, s: Settings):
        self._sessions = sessions
        self._queue = queue
        self._launcher = launcher
        self._s = s

    def recover(self) -> int:
        """Return ids a previous dispatcher process popped but never acknowledged."""
        n = self._queue.recover()
        if n:
            log.info("recovered %d unacknowledged trial(s) from the processing list", n)
        return n

    def active_attempts(self) -> int:
        with self._sessions() as db:
            return db.scalar(select(func.count()).select_from(Attempt).where(Attempt.status.in_(ATTEMPT_ACTIVE)))

    def dispatch_once(self) -> bool:
        """Launch at most one trial. Returns True if a trial id was consumed from the queue."""
        if self.active_attempts() >= self._s.max_concurrency:
            return False
        trial_id = self._queue.pop(timeout=5)
        if trial_id is None:
            return False
        try:
            self._dispatch(trial_id)
        except Exception:
            log.exception("dispatch failed for trial %s; returning it to the queue", trial_id)
            self._queue.nack(trial_id)
            return False
        self._queue.ack(trial_id)
        return True

    def _dispatch(self, trial_id: int) -> None:
        with self._sessions() as db:
            trial = db.get(Trial, trial_id)
            if trial is None or trial.status in TRIAL_TERMINAL:
                log.info("trial %s is %s; dropping duplicate delivery", trial_id, trial and trial.status)
                return
            attempt = next((a for a in trial.attempts if a.status in ATTEMPT_ACTIVE), None)
            if attempt is None:
                number = len(trial.attempts) + 1
                attempt = Attempt(trial=trial, number=number, job_name=f"trial-{trial.id}-a{number}")
                trial.status = "dispatched"
                db.add(attempt)
                db.commit()  # the attempt exists before its Job, so a crash here is recoverable
            # Relaunching an existing active attempt is safe: same Job name, create is idempotent.
            self._launcher.launch(
                attempt.job_name, trial.id, attempt.number, attempt.callback_token, trial.run.deadline_seconds
            )
            if attempt.status == "created":
                attempt.status = "launched"
                db.commit()
            log.info("trial %s attempt %s launched as %s", trial.id, attempt.number, attempt.job_name)

    def reconcile(self) -> list[int]:
        """Settle attempts whose Job ended without a callback. Returns trial ids re-queued for retry."""
        requeue: list[int] = []
        with self._sessions() as db:
            attempts = db.scalars(select(Attempt).where(Attempt.status.in_(("launched", "running")))).all()
            for attempt in attempts:
                state = self._launcher.job_state(attempt.job_name)
                if state == "active":
                    continue
                if state == "missing" and utcnow() - _aware(attempt.created_at) < timedelta(
                    seconds=self._s.missing_job_grace_seconds
                ):
                    continue  # the Job may not be visible yet
                trial = attempt.trial
                attempt.finished_at = utcnow()
                if state == "deadline":
                    attempt.status, attempt.reason = "timed_out", "deadline exceeded"
                    _finish_trial(trial, "errored", "agent", "deadline exceeded")
                    continue
                attempt.status = "infra_failed"
                attempt.reason = f"job {state} without a result callback"
                infra_failures = sum(1 for a in trial.attempts if a.status == "infra_failed")
                if infra_failures <= self._s.max_infra_retries:
                    trial.status = "queued"
                    requeue.append(trial.id)
                else:
                    _finish_trial(trial, "infra_failed", "infra", attempt.reason)
                log.warning("trial %s attempt %s: %s", trial.id, attempt.number, attempt.reason)
            db.commit()
        for trial_id in requeue:  # only after the commit, so a retry never races its own bookkeeping
            self._queue.push(trial_id)
        return requeue


def _finish_trial(trial: Trial, status: str, failure_class: str, error: str) -> None:
    trial.status = status
    trial.failure_class = failure_class
    trial.error = error
    trial.finished_at = utcnow()


def _aware(dt):
    # SQLite returns naive datetimes; treat them as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


def main() -> None:
    from app.db import SessionLocal
    from app.k8s import JobLauncher

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    d = Dispatcher(SessionLocal, RedisTrialQueue(settings.redis_url, settings.queue_name), JobLauncher(settings), settings)
    log.info("dispatcher up: namespace=%s max_concurrency=%d", settings.namespace, settings.max_concurrency)
    while True:  # Redis may still be starting; recovery must happen before any new dispatch
        try:
            d.recover()
            break
        except Exception:
            log.exception("recovery failed; retrying")
            time.sleep(2)
    last_reconcile = 0.0
    while True:
        try:
            if time.monotonic() - last_reconcile >= settings.reconcile_interval_seconds:
                d.reconcile()
                last_reconcile = time.monotonic()
            launched = d.dispatch_once()
        except Exception:
            # Redis, Postgres or the Kubernetes API briefly unavailable: back off, don't crash.
            log.exception("dispatch loop error; retrying")
            launched = False
            time.sleep(4)
        if not launched:
            time.sleep(1)


if __name__ == "__main__":
    main()
