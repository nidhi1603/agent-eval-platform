import secrets
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


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
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    trials: Mapped[list["Trial"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Trial(Base):
    """One attempt of one task. Status: queued -> running -> completed | errored."""

    __tablename__ = "trials"
    __table_args__ = (UniqueConstraint("run_id", "task_id", "trial_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str] = mapped_column(String(200))
    trial_index: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)

    # Per-trial secret the pod presents when calling back; the pod gets no DB or k8s credentials.
    callback_token: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_urlsafe(24))

    reward: Mapped[float | None]
    cost_usd: Mapped[float | None]
    n_turns: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(String(4000))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]

    run: Mapped[Run] = relationship(back_populates="trials")
