from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RunCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    agent: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=100)
    model: str | None = None
    task_ids: list[str] = Field(min_length=1, max_length=1000)
    k: int = Field(default=1, ge=1, le=8)
    deadline_seconds: int | None = Field(default=None, ge=10, le=3600)


class RunSummary(BaseModel):
    id: int
    name: str
    agent: str
    domain: str
    model: str | None
    k: int
    created_at: datetime
    status_counts: dict[str, int]
    # Over trials with an agent outcome (completed or errored; errored counts as failure).
    # infra_failed trials are excluded and visible in status_counts.
    pass_hat_k: dict[int, float | None]
    attempts: int
    spend_usd: float  # every attempt's reported cost, including retried and late attempts


class TrialOut(BaseModel):
    id: int
    task_id: str
    trial_index: int
    status: str
    reward: float | None
    cost_usd: float | None
    n_turns: int | None
    error: str | None
    failure_class: str | None
    attempts: int
    started_at: datetime | None
    finished_at: datetime | None


class TrialSpec(BaseModel):
    """What a trial pod needs to run: returned when it checks in."""

    trial_id: int
    attempt: int
    run_id: int
    task_id: str
    trial_index: int
    agent: str
    domain: str
    model: str | None


class TrialResult(BaseModel):
    status: Literal["completed", "errored"]
    reward: float | None = None
    cost_usd: float | None = None
    n_turns: int | None = None
    error: str | None = Field(default=None, max_length=4000)
