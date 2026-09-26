from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_session
from app.dispatcher import Dispatcher
from app.main import app, get_queue
from app.settings import Settings


class Crash(BaseException):
    """Simulates the dispatcher process dying: not caught by `except Exception`."""


class FakeQueue:
    """In-memory equivalent of RedisTrialQueue, including the processing list."""

    def __init__(self):
        self.queue: list[int] = []
        self.processing: list[int] = []
        self.crash_on_ack = False

    def push(self, trial_id):
        self.queue.append(trial_id)

    def pop(self, timeout):
        if not self.queue:
            return None
        item = self.queue.pop(0)
        self.processing.append(item)
        return item

    def ack(self, trial_id):
        if self.crash_on_ack:
            self.crash_on_ack = False
            raise Crash("died after launch, before ack")
        self.processing.remove(trial_id)

    def nack(self, trial_id):
        self.processing.remove(trial_id)
        self.queue.insert(0, trial_id)

    def recover(self):
        n = len(self.processing)
        self.queue[:0] = self.processing
        self.processing = []
        return n


class FakeLauncher:
    """Records Jobs by name; tests set how each Job ended."""

    def __init__(self):
        self.jobs: dict[str, str] = {}
        self.launch_calls: list[str] = []
        self.crash_on_launch = False

    def launch(self, name, trial_id, attempt, token, deadline_seconds):
        if self.crash_on_launch:
            self.crash_on_launch = False
            raise Crash("died before creating the Job")
        self.launch_calls.append(name)
        self.jobs.setdefault(name, "active")  # same name again = Kubernetes 409, a no-op

    def job_state(self, name):
        return self.jobs.get(name, "missing")


@dataclass
class Env:
    client: TestClient
    sessions: sessionmaker
    queue: FakeQueue
    launcher: FakeLauncher
    settings: Settings
    _dispatcher: Dispatcher | None = field(default=None)

    def dispatcher(self, fresh: bool = False) -> Dispatcher:
        """fresh=True models a restarted dispatcher process (same Redis, DB and cluster)."""
        if fresh or self._dispatcher is None:
            self._dispatcher = Dispatcher(self.sessions, self.queue, self.launcher, self.settings)
        return self._dispatcher

    def create_run(self, task_ids=("t1", "t2"), k=2, agent="stub"):
        body = {"name": "test", "agent": agent, "domain": "mock", "task_ids": list(task_ids), "k": k}
        r = self.client.post("/runs", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def token(self, trial_id, attempt_number=None):
        from app.models import Trial
        with self.sessions() as db:
            attempts = db.get(Trial, trial_id).attempts
            a = attempts[-1] if attempt_number is None else attempts[attempt_number - 1]
            return a.callback_token

    def start(self, trial_id, token):
        return self.client.post(f"/trials/{trial_id}/start", headers={"x-trial-token": token})

    def result(self, trial_id, token, reward=1.0, status="completed", cost=0.01):
        return self.client.post(f"/trials/{trial_id}/result", headers={"x-trial-token": token},
                                json={"status": status, "reward": reward, "cost_usd": cost})

    def run_summary(self, run_id):
        return self.client.get(f"/runs/{run_id}").json()


@pytest.fixture
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    queue, launcher = FakeQueue(), FakeLauncher()

    def session_override():
        with sessions() as s:
            yield s

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_queue] = lambda: queue
    s = Settings(max_concurrency=100, max_infra_retries=1, missing_job_grace_seconds=60)
    yield Env(TestClient(app), sessions, queue, launcher, s)
    app.dependency_overrides.clear()
