import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.main import app, get_queue
from app.queue import QueuedTrial


class FakeQueue:
    def __init__(self):
        self.items: list[QueuedTrial] = []

    def push(self, item):
        self.items.append(item)

    def push_front(self, item):
        self.items.insert(0, item)

    def pop(self, timeout):
        return self.items.pop(0) if self.items else None


@pytest.fixture
def ctx():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    queue = FakeQueue()

    def session_override():
        with Session() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_queue] = lambda: queue
    yield TestClient(app), queue
    app.dependency_overrides.clear()


def create_run(client, task_ids=("t1", "t2"), k=2):
    body = {"name": "smoke", "agent": "stub", "domain": "mock", "task_ids": list(task_ids), "k": k}
    r = client.post("/runs", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def finish(client, item, reward):
    h = {"x-trial-token": item.callback_token}
    assert client.post(f"/trials/{item.trial_id}/start", headers=h).status_code == 200
    r = client.post(f"/trials/{item.trial_id}/result", headers=h, json={"status": "completed", "reward": reward, "cost_usd": 0.01})
    assert r.status_code == 200, r.text


def test_create_run_enqueues_task_times_k_trials(ctx):
    client, queue = ctx
    run = create_run(client, task_ids=("t1", "t2", "t2"), k=3)  # duplicate task ids collapse
    assert run["status_counts"] == {"queued": 6}
    assert len(queue.items) == 6
    assert len({i.callback_token for i in queue.items}) == 6


def test_trial_lifecycle_and_pass_hat_k(ctx):
    client, queue = ctx
    run = create_run(client)
    items = list(queue.items)
    for item, reward in zip(items, [1.0, 1.0, 1.0, 0.0]):  # t1 passes twice, t2 passes once
        finish(client, item, reward)

    summary = client.get(f"/runs/{run['id']}").json()
    assert summary["status_counts"] == {"completed": 4}
    assert summary["pass_hat_k"]["1"] == pytest.approx(0.75)
    assert summary["pass_hat_k"]["2"] == pytest.approx(0.5)
    assert summary["total_cost_usd"] == pytest.approx(0.04)


def test_callback_requires_the_trials_own_token(ctx):
    client, queue = ctx
    create_run(client)
    a, b = queue.items[0], queue.items[1]
    assert client.post(f"/trials/{a.trial_id}/start").status_code == 403
    assert client.post(f"/trials/{a.trial_id}/start", headers={"x-trial-token": b.callback_token}).status_code == 403
    assert client.post("/trials/9999/start", headers={"x-trial-token": a.callback_token}).status_code == 403


def test_finished_trial_cannot_be_rewritten(ctx):
    client, queue = ctx
    create_run(client)
    item = queue.items[0]
    finish(client, item, 1.0)
    h = {"x-trial-token": item.callback_token}
    r = client.post(f"/trials/{item.trial_id}/result", headers=h, json={"status": "completed", "reward": 0.0})
    assert r.status_code == 409
