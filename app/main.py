import asyncio
import hmac
import logging
from collections import Counter
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import Base, engine, get_session
from app.metrics import run_pass_hat_k
from app.models import TRIAL_TERMINAL, Attempt, Run, Trial, utcnow
from app.queue import RedisTrialQueue, TrialQueue
from app.schemas import RunCreate, RunSummary, TrialOut, TrialResult, TrialSpec
from app.settings import settings

log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The database may still be starting when the API pod boots; retry instead of crash-looping.
    for attempt in range(30):
        try:
            Base.metadata.create_all(engine)
            break
        except OperationalError:
            if attempt == 29:
                raise
            await asyncio.sleep(2)
    yield


app = FastAPI(title="Agent Eval Platform", version="0.2.0", lifespan=lifespan)

SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache
def get_queue() -> TrialQueue:
    return RedisTrialQueue(settings.redis_url, settings.queue_name)


QueueDep = Annotated[TrialQueue, Depends(get_queue)]


def summarize(run: Run) -> RunSummary:
    # Agent outcomes only: an errored trial is a failure (reward 0); infra_failed trials are excluded.
    scored = [(t.task_id, t.reward if t.status == "completed" else 0.0)
              for t in run.trials if t.status in ("completed", "errored")]
    attempts = [a for t in run.trials for a in t.attempts]
    return RunSummary(
        id=run.id,
        name=run.name,
        agent=run.agent,
        domain=run.domain,
        model=run.model,
        k=run.k,
        created_at=run.created_at,
        status_counts=dict(Counter(t.status for t in run.trials)),
        pass_hat_k={k: run_pass_hat_k(scored, k) for k in range(1, run.k + 1)},
        attempts=len(attempts),
        spend_usd=round(sum(a.cost_usd or 0.0 for a in attempts), 6),
    )


def trial_out(t: Trial) -> TrialOut:
    return TrialOut(
        id=t.id, task_id=t.task_id, trial_index=t.trial_index, status=t.status, reward=t.reward,
        cost_usd=t.cost_usd, n_turns=t.n_turns, error=t.error, failure_class=t.failure_class,
        attempts=len(t.attempts), started_at=t.started_at, finished_at=t.finished_at,
    )


def get_run_or_404(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


def authorize_attempt(session: Session, trial_id: int, token: str | None) -> Attempt:
    """Find the attempt this token belongs to. Unknown trial and bad token look identical (403)."""
    trial = session.get(Trial, trial_id)
    if trial is not None and token is not None:
        for attempt in trial.attempts:
            if hmac.compare_digest(attempt.callback_token, token):
                return attempt
    raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid trial token")


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(body: RunCreate, session: SessionDep, queue: QueueDep) -> RunSummary:
    run = Run(name=body.name, agent=body.agent, domain=body.domain, model=body.model, k=body.k,
              deadline_seconds=body.deadline_seconds)
    run.trials = [
        Trial(task_id=task_id, trial_index=i) for task_id in dict.fromkeys(body.task_ids) for i in range(body.k)
    ]
    session.add(run)
    session.commit()
    for t in run.trials:
        queue.push(t.id)
    return summarize(run)


@app.get("/runs")
def list_runs(session: SessionDep) -> list[RunSummary]:
    return [summarize(r) for r in session.scalars(select(Run).order_by(Run.id.desc())).all()]


@app.get("/runs/{run_id}")
def get_run(run_id: int, session: SessionDep) -> RunSummary:
    return summarize(get_run_or_404(session, run_id))


@app.get("/runs/{run_id}/trials")
def list_trials(run_id: int, session: SessionDep) -> list[TrialOut]:
    run = get_run_or_404(session, run_id)
    return [trial_out(t) for t in sorted(run.trials, key=lambda t: t.id)]


@app.post("/trials/{trial_id}/start")
def start_trial(
    trial_id: int, session: SessionDep, x_trial_token: Annotated[str | None, Header()] = None
) -> TrialSpec:
    attempt = authorize_attempt(session, trial_id, x_trial_token)
    trial = attempt.trial
    if trial.status in TRIAL_TERMINAL or attempt.status not in ("created", "launched"):
        # A superseded attempt (e.g. settled by the reconciler) must not run the task again.
        raise HTTPException(status.HTTP_409_CONFLICT, f"attempt {attempt.number} is {attempt.status}")
    now = utcnow()
    attempt.status, attempt.started_at = "running", now
    trial.status = "running"
    trial.started_at = trial.started_at or now
    session.commit()
    run = trial.run
    return TrialSpec(trial_id=trial.id, attempt=attempt.number, run_id=run.id, task_id=trial.task_id,
                     trial_index=trial.trial_index, agent=run.agent, domain=run.domain, model=run.model)


@app.post("/trials/{trial_id}/result")
def report_result(
    trial_id: int,
    body: TrialResult,
    session: SessionDep,
    x_trial_token: Annotated[str | None, Header()] = None,
) -> TrialOut:
    attempt = authorize_attempt(session, trial_id, x_trial_token)
    trial = attempt.trial
    if attempt.status != "running" or trial.status in TRIAL_TERMINAL:
        # Duplicate or late callback. The result is not counted, but money spent is still recorded once.
        if body.cost_usd is not None and attempt.cost_usd is None:
            attempt.cost_usd = body.cost_usd
            session.commit()
        log.warning("rejected callback for trial %s attempt %s (%s)", trial.id, attempt.number, attempt.status)
        raise HTTPException(status.HTTP_409_CONFLICT, f"attempt {attempt.number} is {attempt.status}")
    now = utcnow()
    attempt.status, attempt.finished_at, attempt.cost_usd = body.status, now, body.cost_usd
    trial.status = body.status
    trial.reward = body.reward
    trial.cost_usd = body.cost_usd
    trial.n_turns = body.n_turns
    trial.error = body.error
    trial.failure_class = "agent" if body.status == "errored" else None
    trial.finished_at = now
    session.commit()
    return trial_out(trial)
