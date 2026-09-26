"""Reproductions of known platform defects (see docs/DEFECTS.md).

Each test asserts the CORRECT behavior and is marked xfail(strict=True): it fails today, which
reproduces the defect. When a fix lands the test starts passing, strict xfail turns that into a
failure, and the marker must be removed. The cluster must not be used for scored experiments
while any of these is still marked xfail.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

import app.main
from app.models import Attempt, Trial
from app.schemas import TrialResult
from tests.conftest import Crash

HELM = Path(__file__).resolve().parent.parent / "deploy" / "helm" / "agent-eval" / "templates"


def defect(n: int, what: str):
    return pytest.mark.xfail(strict=True, reason=f"DEFECT-{n}: {what}")


def attempt_statuses(env, trial_id):
    with env.sessions() as db:
        return [a.status for a in db.get(Trial, trial_id).attempts]


@defect(1, "a created-but-unlaunched attempt counts toward the cap, so at full capacity it is never launched")
def test_created_attempt_is_recovered_at_full_capacity(env):
    env.settings.max_concurrency = 1
    env.create_run(task_ids=("t1",), k=1)
    env.launcher.crash_on_launch = True  # dies after committing attempt 1, before creating its Job
    with pytest.raises(Crash):
        env.dispatcher().dispatch_once()

    restarted = env.dispatcher(fresh=True)
    restarted.recover()
    assert restarted.dispatch_once()  # today: the cap check sees 1 "active" attempt and returns False forever
    assert attempt_statuses(env, 1) == ["launched"]


@defect(2, "trials are committed to the DB and then pushed to Redis; a lost push strands them in 'queued'")
def test_trial_whose_enqueue_was_lost_is_eventually_dispatched(env):
    real_push = env.queue.push

    def lost_push(trial_id):
        raise ConnectionError("redis unavailable after the DB commit")

    env.queue.push = lost_push
    with pytest.raises(ConnectionError):
        env.create_run(task_ids=("t1",), k=1)
    env.queue.push = real_push

    d = env.dispatcher()
    d.reconcile()
    d.dispatch_once()
    assert attempt_statuses(env, 1) == ["launched"]  # today: no attempt, the trial is queued forever


@defect(3, "dispatch/start race: the dispatcher's 'launched' write overwrites the pod's 'running'")
def test_fast_pod_start_is_not_overwritten_by_dispatcher(env):
    env.create_run(task_ids=("t1",), k=1)
    real_launch = env.launcher.launch

    def launch_and_start_immediately(name, trial_id, attempt, token, deadline):
        real_launch(name, trial_id, attempt, token, deadline)
        assert env.start(trial_id, token).status_code == 200  # pod checks in before the dispatcher commits

    env.launcher.launch = launch_and_start_immediately
    env.dispatcher().dispatch_once()
    r = env.result(1, env.token(1))
    assert r.status_code == 200, r.text  # today: 409, attempt was reset to 'launched', a valid result is lost


@defect(4, "reconcile/result race: reconcile settles an attempt as infra_failed after its result committed")
def test_result_committed_during_reconcile_is_not_overwritten(env):
    env.create_run(task_ids=("t1",), k=1)
    d = env.dispatcher()
    d.dispatch_once()
    token = env.token(1)
    env.start(1, token)

    def job_finished_after_posting_result(name):
        env.result(1, token, reward=1.0)  # the pod reports, then exits 0
        return "succeeded"

    env.launcher.job_state = job_finished_after_posting_result
    d.reconcile()
    with env.sessions() as db:
        t = db.get(Trial, 1)
        assert (t.status, t.reward, len(t.attempts)) == ("completed", 1.0, 1)  # today: infra_failed + retried


@defect(5, "concurrent callbacks for one attempt both pass the status check and both write")
def test_concurrent_duplicate_callbacks_accept_exactly_one(env, monkeypatch):
    env.create_run(task_ids=("t1",), k=1)
    env.dispatcher().dispatch_once()
    token = env.token(1)
    env.start(1, token)

    real_utcnow = app.main.utcnow
    inner = {}

    def utcnow_with_interleaved_callback():
        # report_result calls utcnow() after its status check and before its writes: run the
        # second callback (same endpoint function, its own DB session) exactly there.
        if not inner:
            inner["status"] = 0
            with env.sessions() as db:
                try:
                    app.main.report_result(1, TrialResult(status="completed", reward=0.0), db, token)
                    inner["status"] = 200
                except HTTPException as e:
                    inner["status"] = e.status_code
        return real_utcnow()

    monkeypatch.setattr(app.main, "utcnow", utcnow_with_interleaved_callback)
    outer = env.result(1, token, reward=1.0)
    assert sorted([outer.status_code, inner["status"]]) == [200, 409]  # today: [200, 200], last write wins


@defect(6, "reward, cost and turn values are not range-checked")
@pytest.mark.parametrize("field,value", [("reward", -5.0), ("reward", 7.0), ("cost_usd", -1.0), ("n_turns", -3)])
def test_invalid_result_values_are_rejected(env, field, value):
    env.create_run(task_ids=("t1",), k=1)
    env.dispatcher().dispatch_once()
    token = env.token(1)
    env.start(1, token)
    body = {"status": "completed", "reward": 1.0, "cost_usd": 0.01, field: value}
    r = env.client.post("/trials/1/result", headers={"x-trial-token": token}, json=body)
    assert r.status_code == 422  # today: 200 and the value is stored


@defect(7, "a lost /result response cannot be retried: the identical retry gets 409")
def test_identical_result_retry_is_acknowledged(env):
    env.create_run(task_ids=("t1",), k=1)
    env.dispatcher().dispatch_once()
    token = env.token(1)
    env.start(1, token)
    assert env.result(1, token, reward=1.0).status_code == 200  # applied, but the pod never saw the response
    assert env.result(1, token, reward=1.0).status_code == 200  # today: 409, so the pod exits non-zero


@defect(7, "a lost /start response cannot be retried: the retry gets 409 and the pod exits without running")
def test_start_retry_returns_the_spec_again(env):
    env.create_run(task_ids=("t1",), k=1)
    env.dispatcher().dispatch_once()
    token = env.token(1)
    assert env.start(1, token).status_code == 200
    assert env.start(1, token).status_code == 200  # today: 409


@defect(8, "two dispatchers (e.g. during a rolling update) can both pass the cap check")
def test_overlapping_dispatchers_respect_the_cap(env):
    env.settings.max_concurrency = 1
    env.create_run(task_ids=("t1", "t2"), k=1)
    d1, d2 = env.dispatcher(), env.dispatcher(fresh=True)
    real_count = d1.active_attempts

    def stale_count():
        n = real_count()
        d2.dispatch_once()  # the other dispatcher launches between d1's check and d1's launch
        return n

    d1.active_attempts = stale_count
    d1.dispatch_once()
    with env.sessions() as db:
        active = db.query(Attempt).filter(Attempt.status.in_(("created", "launched", "running"))).count()
    assert active <= 1  # today: 2


@defect(8, "the dispatcher Deployment uses the default RollingUpdate strategy and has no leader lock")
def test_dispatcher_deployment_cannot_overlap():
    assert "Recreate" in (HELM / "dispatcher.yaml").read_text()


@defect(9, "dev Postgres and Redis write to the container filesystem with no volume")
def test_datastores_are_durable():
    text = (HELM / "datastores.yaml").read_text()
    assert text.count("persistentVolumeClaim") >= 1  # at least Postgres; Redis may be rebuilt from Postgres (fix 2)
