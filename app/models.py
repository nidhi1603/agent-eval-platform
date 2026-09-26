import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Trial lifecycle: queued -> dispatched -> running -> completed | errored | infra_failed.
# completed/errored are agent outcomes and count in metrics (errored = failure).
# infra_failed means the platform could not produce a result; excluded from metrics, reported separately.
TRIAL_TERMINAL = ("completed", "errored", "infra_failed")

# Attempt lifecycle: created -> launched -> running -> completed | errored | timed_out | infra_failed.
ATTEMPT_ACTIVE = ("created", "launched", "running")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """One benchmark run: an agent configuration evaluated on a task set, k trials per task."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    agent: Mapped[str] = mapped_column(String(100))
    domain: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    k: Mapped[int]
    deadline_seconds: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    trials: Mapped[list["Trial"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Trial(Base):
    """One scored attempt slot for one task. Its result comes from its final attempt."""

    __tablename__ = "trials"
    __table_args__ = (UniqueConstraint("run_id", "task_id", "trial_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str] = mapped_column(String(200))
    trial_index: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)

    reward: Mapped[float | None]
    cost_usd: Mapped[float | None]
    n_turns: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(String(4000))
    failure_class: Mapped[str | None] = mapped_column(String(10))  # "agent" | "infra"
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    run: Mapped[Run] = relationship(back_populates="trials")
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="trial", cascade="all, delete-orphan", order_by="Attempt.number"
    )


class Attempt(Base):
    """One execution of a trial as a Kubernetes Job. A trial may need several after infra failures."""

    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("trial_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trial_id: Mapped[int] = mapped_column(ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    number: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)
    job_name: Mapped[str] = mapped_column(String(63))
    # Secret the pod presents when calling back; the pod gets no DB or k8s credentials.
    callback_token: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_urlsafe(24))
    reason: Mapped[str | None] = mapped_column(String(500))
    # Spend actually incurred, even if the attempt's result is not counted (e.g. a late callback).
    cost_usd: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    trial: Mapped[Trial] = relationship(back_populates="attempts")
