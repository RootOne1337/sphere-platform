"""Generation fencing shared by the executor and SQL-writing step handlers."""

import asyncio
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline import PipelineRun, PipelineRunStatus


class PipelineLeaseLost(asyncio.CancelledError):
    """Control flow, not a failed step eligible for retry."""


class PipelineSuspended(asyncio.CancelledError):
    """A durable waiting checkpoint replaced this coroutine, not a step failure."""


@dataclass(frozen=True)
class Ownership:
    run_id: uuid.UUID
    owner: uuid.UUID
    generation: int
    session_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    org_id: uuid.UUID | None = None


current_ownership: ContextVar[Ownership | None] = ContextVar("pipeline_ownership", default=None)
scheduled_generation: ContextVar[int | None] = ContextVar("pipeline_scheduled_generation", default=None)
scheduled_tenant: ContextVar[uuid.UUID | None] = ContextVar("pipeline_scheduled_tenant", default=None)


async def database_now(db: AsyncSession) -> datetime:
    # PostgreSQL now() is the transaction start, which can predate a long lock
    # wait. Fencing needs the clock *after* the lock has been acquired.
    clock = func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.current_timestamp()
    value = await db.scalar(select(clock))
    assert isinstance(value, datetime)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def fence_write(db: AsyncSession, run: PipelineRun) -> None:
    """Hold the row lock through the caller's write; don't trust a cached ORM row."""
    await db.refresh(run, with_for_update=True)
    ownership = current_ownership.get()
    if ownership is None:
        return  # Standalone handler tests; every executor establishes ownership.
    now = await database_now(db)
    if (
        run.id != ownership.run_id or run.execution_owner != ownership.owner
        or run.execution_generation != ownership.generation
        or run.execution_lease_until is None or run.execution_lease_until <= now
        or run.status not in (PipelineRunStatus.RUNNING, PipelineRunStatus.PAUSED)
    ):
        raise PipelineLeaseLost("Pipeline owner or generation changed")


def is_checkpointed_child(step: dict, run: PipelineRun) -> bool:
    ownership = current_ownership.get()
    return bool(ownership and ownership.run_id == run.id and step.get("id") == run.current_step_id)
