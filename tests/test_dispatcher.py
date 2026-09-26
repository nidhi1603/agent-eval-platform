"""Failure injection: every recovery guarantee in app/dispatcher.py has a test here."""

from datetime import timedelta

import pytest

from app.models import Attempt, Trial, utcnow
from tests.conftest import Crash


def attempts_of(env, trial_id):
    with env.sessions() as db:
        return [(a.number, a.status) for a in db.get(Trial, trial_id).attempts]


def trial_status(env, trial_id):
    with env.sessions() as db:
        t = db.get(Trial, trial_id)
        return t.status, t.failure_class


def test_dispatcher_crash_between_pop_and_launch_loses_nothing(env):
    env.create_run(task_ids=("t1",), k=1)
    env.launcher.crash_on_launch = True
    with pytest.raises(Crash):
        env.dispatcher().dispatch_once()
    assert env.queue.queue == [] and env.queue.processing == [1]  # held in Redis, not only in memory

    restarted = env.dispatcher(fresh=True)
    assert restarted.recover() == 1
    assert restarted.dispatch_once()
    assert attempts_of(env, 1) == [(1, "launched")]
    assert env.launcher.launch_calls == ["trial-1-a1"]


def test_dispatcher_crash_after_launch_before_ack_does_not_duplicate(env):
    env.create_run(task_ids=("t1",), k=1)
    env.queue.crash_on_ack = True
    with pytest.raises(Crash):
        env.dispatcher().dispatch_once()

    restarted = env.dispatcher(fresh=True)
    restarted.recover()
    restarted.dispatch_once()
    assert attempts_of(env, 1) == [(1, "launched")]  # still exactly one attempt
    assert set(env.launcher.jobs) == {"trial-1-a1"}  # the relaunch reused the same Job name


def test_duplicate_queue_delivery_is_ignored(env):
    env.create_run(task_ids=("t1",), k=1)
    env.queue.push(1)  # the same trial delivered twice
    d = env.dispatcher()
    d.dispatch_once()
    d.dispatch_once()
    assert attempts_of(env, 1) == [(1, "launched")]

    token = env.token(1)
    env.start(1, token)
    env.result(1, token)
    env.queue.push(1)  # a stale delivery after the trial finished
    d.dispatch_once()
    assert attempts_of(env, 1) == [(1, "completed")]


def test_worker_crash_is_retried_once_and_counted_once(env):
    run = env.create_run(task_ids=("t1",), k=1)
    d = env.dispatcher()
    d.dispatch_once()
    env.start(1, env.token(1))
    env.launcher.jobs["trial-1-a1"] = "failed"  # pod died without a callback

    assert d.reconcile() == [1]
    assert trial_status(env, 1) == ("queued", None)
    d.dispatch_once()
    token2 = env.token(1, attempt_number=2)
    env.start(1, token2)
    env.result(1, token2, reward=1.0)

    assert attempts_of(env, 1) == [(1, "infra_failed"), (2, "completed")]
    summary = env.run_summary(run["id"])
    assert summary["status_counts"] == {"completed": 1}
    assert summary["pass_hat_k"]["1"] == 1.0  # one trial, counted once
    assert summary["attempts"] == 2


def test_infra_failures_beyond_the_retry_budget_are_excluded_from_metrics(env):
    run = env.create_run(task_ids=("t1", "t2"), k=1)
    d = env.dispatcher()
    d.dispatch_once(); d.dispatch_once()
    token2 = env.token(2)
    env.start(2, token2)
    env.result(2, token2, reward=1.0)
    for attempt in (1, 2):  # trial 1 fails on the original attempt and on its single retry
        env.launcher.jobs[f"trial-1-a{attempt}"] = "failed"
        d.reconcile()
        d.dispatch_once()

    assert trial_status(env, 1) == ("infra_failed", "infra")
    assert attempts_of(env, 1) == [(1, "infra_failed"), (2, "infra_failed")]
    summary = env.run_summary(run["id"])
    assert summary["status_counts"] == {"infra_failed": 1, "completed": 1}
    assert summary["pass_hat_k"]["1"] == 1.0  # computed over trial 2 only; infra failure is not an agent failure


def test_deadline_expiry_is_an_agent_timeout_and_is_not_retried(env):
    run = env.create_run(task_ids=("t1",), k=1)
    d = env.dispatcher()
    d.dispatch_once()
    env.start(1, env.token(1))
    env.launcher.jobs["trial-1-a1"] = "deadline"

    assert d.reconcile() == []
    assert trial_status(env, 1) == ("errored", "agent")
    assert attempts_of(env, 1) == [(1, "timed_out")]
    assert env.run_summary(run["id"])["pass_hat_k"]["1"] == 0.0


def test_missing_job_is_given_a_grace_period(env):
    env.create_run(task_ids=("t1",), k=1)
    d = env.dispatcher()
    d.dispatch_once()
    del env.launcher.jobs["trial-1-a1"]  # Job not visible (yet, or deleted)
    assert d.reconcile() == []
    assert attempts_of(env, 1) == [(1, "launched")]

    with env.sessions() as db:  # the grace period has passed
        db.get(Attempt, 1).created_at = utcnow() - timedelta(seconds=120)
        db.commit()
    assert d.reconcile() == [1]
    assert attempts_of(env, 1) == [(1, "infra_failed")]


def test_late_callback_from_a_superseded_attempt_is_rejected_but_its_spend_is_recorded(env):
    run = env.create_run(task_ids=("t1",), k=1)
    d = env.dispatcher()
    d.dispatch_once()
    token1 = env.token(1, attempt_number=1)
    env.start(1, token1)
    env.launcher.jobs["trial-1-a1"] = "failed"  # e.g. the node was lost, but the pod was slow, not dead
    d.reconcile()
    d.dispatch_once()

    late = env.result(1, token1, reward=1.0, cost=0.05)
    assert late.status_code == 409
    assert trial_status(env, 1)[0] == "dispatched"  # attempt 2 is in flight; attempt 1's result was not applied
    assert env.start(1, token1).status_code == 409  # a superseded attempt can't restart either

    token2 = env.token(1, attempt_number=2)
    env.start(1, token2)
    env.result(1, token2, reward=0.0, cost=0.03)
    summary = env.run_summary(run["id"])
    assert summary["pass_hat_k"]["1"] == 0.0  # the counted result is attempt 2's
    assert summary["spend_usd"] == pytest.approx(0.08)  # both attempts cost money


def test_concurrency_cap_counts_active_attempts(env):
    env.settings.max_concurrency = 1
    env.create_run(task_ids=("t1", "t2"), k=1)
    d = env.dispatcher()
    assert d.dispatch_once()
    assert not d.dispatch_once()  # cap reached while trial 1 is active
    token = env.token(1)
    env.start(1, token)
    env.result(1, token)
    assert d.dispatch_once()
