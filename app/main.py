import asyncio
import hmac
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
from app.models import Run, Trial, utcnow
from app.queue import QueuedTrial, RedisTrialQueue, TrialQueue
from app.schemas import RunCreate, RunSummary, TrialOut, TrialResult, TrialSpec
from app.settings import settings


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


app = FastAPI(title="Agent Eval Platform", version="0.1.0", lifespan=lifespan)

SessionDep = Annotated[Session, Depends(get_session)]


@lru_cache
def get_queue() -> TrialQueue:
    return RedisTrialQueue(settings.redis_url, settings.queue_name)


QueueDep = Annotated[TrialQueue, Depends(get_queue)]


def summarize(run: Run) -> RunSummary:
    completed = [(t.task_id, t.reward) for t in run.trials if t.status == "completed"]
    return RunSummary(
        id=run.id,
        name=run.name,
        agent=run.agent,
        domain=run.domain,
        model=run.model,
        k=run.k,
        created_at=run.created_at,
        status_counts=dict(Counter(t.status for t in run.trials)),
        pass_hat_k={k: run_pass_hat_k(completed, k) for k in range(1, run.k + 1)},
        total_cost_usd=round(sum(t.cost_usd or 0.0 for t in run.trials), 6),
    )


def get_run_or_404(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"run {run_id} not found")
    return run


def authorize_trial(session: Session, trial_id: int, token: str | None) -> Trial:
    trial = session.get(Trial, trial_id)
    # Same response for unknown trial and bad token, so tokens can't be probed.
    if trial is None or token is None or not hmac.compare_digest(trial.callback_token, token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid trial token")
    return trial


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(body: RunCreate, session: SessionDep, queue: QueueDep) -> RunSummary:
    run = Run(name=body.name, agent=body.agent, domain=body.domain, model=body.model, k=body.k)
    run.trials = [
        Trial(task_id=task_id, trial_index=i) for task_id in dict.fromkeys(body.task_ids) for i in range(body.k)
    ]
    session.add(run)
    session.commit()
    for t in run.trials:
        queue.push(QueuedTrial(trial_id=t.id, callback_token=t.callback_token))
    return summarize(run)


@app.get("/runs")
def list_runs(session: SessionDep) -> list[RunSummary]:
    runs = session.scalars(select(Run).order_by(Run.id.desc())).all()
    return [summarize(r) for r in runs]


@app.get("/runs/{run_id}")
def get_run(run_id: int, session: SessionDep) -> RunSummary:
    return summarize(get_run_or_404(session, run_id))


@app.get("/runs/{run_id}/trials")
def list_trials(run_id: int, session: SessionDep) -> list[TrialOut]:
    run = get_run_or_404(session, run_id)
    return [TrialOut.model_validate(t, from_attributes=True) for t in sorted(run.trials, key=lambda t: t.id)]


@app.post("/trials/{trial_id}/start")
def start_trial(
    trial_id: int, session: SessionDep, x_trial_token: Annotated[str | None, Header()] = None
) -> TrialSpec:
    trial = authorize_trial(session, trial_id, x_trial_token)
    if trial.status in ("completed", "errored"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"trial {trial_id} already {trial.status}")
    trial.status = "running"
    trial.started_at = utcnow()
    session.commit()
    run = trial.run
    return TrialSpec(
        trial_id=trial.id,
        run_id=run.id,
        task_id=trial.task_id,
        trial_index=trial.trial_index,
        agent=run.agent,
        domain=run.domain,
        model=run.model,
    )


@app.post("/trials/{trial_id}/result")
def report_result(
    trial_id: int,
    body: TrialResult,
    session: SessionDep,
    x_trial_token: Annotated[str | None, Header()] = None,
) -> TrialOut:
    trial = authorize_trial(session, trial_id, x_trial_token)
    if trial.status in ("completed", "errored"):
        raise HTTPException(status.HTTP_409_CONFLICT, f"trial {trial_id} already {trial.status}")
    trial.status = body.status
    trial.reward = body.reward
    trial.cost_usd = body.cost_usd
    trial.n_turns = body.n_turns
    trial.error = body.error
    trial.finished_at = utcnow()
    session.commit()
    return TrialOut.model_validate(trial, from_attributes=True)
