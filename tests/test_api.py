import pytest


def dispatch_all(env):
    while env.dispatcher().dispatch_once():
        pass


def test_create_run_enqueues_trial_ids_only(env):
    run = env.create_run(task_ids=("t1", "t2", "t2"), k=3)  # duplicate task ids collapse
    assert run["status_counts"] == {"queued": 6}
    assert env.queue.queue == [1, 2, 3, 4, 5, 6]  # ids only: callback tokens never leave the database


def test_trial_lifecycle_and_pass_hat_k(env):
    run = env.create_run()
    dispatch_all(env)
    for trial_id, reward in zip([1, 2, 3, 4], [1.0, 1.0, 1.0, 0.0]):  # t1 passes twice, t2 once
        token = env.token(trial_id)
        assert env.start(trial_id, token).status_code == 200
        assert env.result(trial_id, token, reward=reward).status_code == 200

    summary = env.run_summary(run["id"])
    assert summary["status_counts"] == {"completed": 4}
    assert summary["pass_hat_k"]["1"] == pytest.approx(0.75)
    assert summary["pass_hat_k"]["2"] == pytest.approx(0.5)
    assert summary["spend_usd"] == pytest.approx(0.04)
    assert summary["attempts"] == 4


def test_agent_error_counts_as_failure(env):
    run = env.create_run(task_ids=("t1",), k=2)
    dispatch_all(env)
    for trial_id, status in [(1, "completed"), (2, "errored")]:
        token = env.token(trial_id)
        env.start(trial_id, token)
        env.result(trial_id, token, reward=1.0 if status == "completed" else None, status=status)
    summary = env.run_summary(run["id"])
    assert summary["pass_hat_k"]["1"] == pytest.approx(0.5)
    trials = env.client.get(f"/runs/{run['id']}/trials").json()
    assert trials[1]["failure_class"] == "agent"


def test_callback_requires_the_attempts_own_token(env):
    env.create_run()
    dispatch_all(env)
    a, b = env.token(1), env.token(2)
    assert env.client.post("/trials/1/start").status_code == 403
    assert env.start(1, b).status_code == 403
    assert env.start(9999, a).status_code == 403


def test_duplicate_result_callback_is_rejected_not_overwritten(env):
    run = env.create_run(task_ids=("t1",), k=1)
    dispatch_all(env)
    token = env.token(1)
    env.start(1, token)
    assert env.result(1, token, reward=1.0).status_code == 200
    assert env.result(1, token, reward=0.0).status_code == 409
    assert env.run_summary(run["id"])["pass_hat_k"]["1"] == 1.0
