"""Read-only trigger decisions shared by simulation and admission."""

from __future__ import annotations

import fnmatch
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device_event import DeviceEvent
from backend.models.event_trigger import EventTrigger
from backend.models.pipeline import Pipeline, PipelineRun
from backend.schemas.event_trigger import EventTriggerSimulationResponse, TriggerDecisionReason

HOUR = timedelta(hours=1)
MAX_CAUSE_DEPTH = 8
MAX_ROOT_RUNS = 32


async def trigger_clock(db: AsyncSession) -> datetime:
    # A lock wait must not preserve the previous statement/transaction clock.
    # SQLite is used by the local API fixture; PostgreSQL is the runtime store.
    if db.bind is not None and db.bind.dialect.name == "sqlite":
        return datetime.now(timezone.utc)
    now = await db.scalar(select(func.clock_timestamp()))
    if not isinstance(now, datetime):
        raise RuntimeError("Trigger database clock unavailable")
    return now


def trigger_pattern_matches(event_type: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(event_type, pattern)


async def inspect_trigger(
    db: AsyncSession, trigger: EventTrigger, event_type: str, now: datetime, *,
    pipeline_active: bool, count_unlimited: bool = False, event: DeviceEvent | None = None,
    root_available: bool = True,
) -> EventTriggerSimulationResponse:
    count, retry_at = 0, None
    if count_unlimited or trigger.max_triggers_per_hour > 0:
        runs = select(PipelineRun.trigger_accepted_at).where(
            PipelineRun.org_id == trigger.org_id,
            PipelineRun.event_trigger_id == trigger.id,
            PipelineRun.trigger_accepted_at > now - HOUR,
        )
        total = select(func.count()).select_from(runs.subquery()).scalar_subquery()
        if trigger.max_triggers_per_hour > 0:
            # If an operator lowered the limit, enough runs must expire to make
            # room, not merely the oldest one in the current window.
            last_blocking_run = runs.order_by(PipelineRun.trigger_accepted_at.desc()).offset(
                trigger.max_triggers_per_hour - 1,
            ).limit(1).scalar_subquery()
            count, expires = (await db.execute(select(total, last_blocking_run))).one()
            if expires is not None:
                retry_at = (expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)) + HOUR
        else:
            count = await db.scalar(select(total)) or 0

    root_id, depth, root_runs = None, None, None
    path: list[str] = []
    duplicate = False
    if event is not None:
        root_id = event.trigger_root_event_id or event.id
        path = event.trigger_path or []
        depth = len(path)
        duplicate, root_runs = await _stored_admission(db, trigger, event, root_id)

    matches = trigger_pattern_matches(event_type, trigger.event_type_pattern)
    reason: TriggerDecisionReason = "eligible"
    if not matches:
        reason = "pattern_mismatch"
    elif not trigger.is_active:
        reason = "trigger_disabled"
    elif not pipeline_active:
        reason = "pipeline_unavailable"
    elif duplicate:
        reason = "duplicate_event"
    elif not root_available:
        reason = "cause_unavailable"
    elif str(trigger.id) in path:
        reason = "causal_cycle"
    elif depth is not None and depth >= MAX_CAUSE_DEPTH:
        reason = "depth_limit"
    elif root_runs is not None and root_runs >= MAX_ROOT_RUNS:
        reason = "root_limit"
    else:
        cooldown_at = None
        if trigger.last_triggered_at is not None and trigger.cooldown_seconds > 0:
            previous = trigger.last_triggered_at
            if previous.tzinfo is None:
                previous = previous.replace(tzinfo=timezone.utc)
            cooldown_at = previous + timedelta(seconds=trigger.cooldown_seconds)
        if cooldown_at is not None and cooldown_at > now and (retry_at is None or cooldown_at >= retry_at):
            reason, retry_at = "cooldown", cooldown_at
        elif retry_at is not None:
            reason = "hour_limit"
    return EventTriggerSimulationResponse(
        trigger_id=trigger.id, event_type=event_type, matches=matches, would_admit=reason == "eligible",
        reason=reason, observed_at=now, retry_at=retry_at if reason in ("cooldown", "hour_limit") else None,
        recent_runs=count, max_triggers_per_hour=trigger.max_triggers_per_hour,
        event_id=event.id if event is not None else None,
        event_origin=("pipeline" if event.trigger_path is not None else "independent") if event is not None else None,
        root_event_id=root_id, cause_depth=depth, max_cause_depth=MAX_CAUSE_DEPTH,
        root_runs=root_runs, max_root_runs=MAX_ROOT_RUNS,
    )


async def _stored_admission(
    db: AsyncSession, trigger: EventTrigger, event: DeviceEvent, root_id: uuid.UUID,
) -> tuple[bool, int]:
    duplicate = select(PipelineRun.id).where(
        PipelineRun.org_id == trigger.org_id,
        PipelineRun.event_trigger_id == trigger.id,
        PipelineRun.trigger_event_id == event.id,
    ).exists()
    count = select(func.count()).select_from(PipelineRun).where(
        PipelineRun.org_id == trigger.org_id, PipelineRun.event_trigger_id.is_not(None),
        or_(
            PipelineRun.trigger_root_event_id == root_id,
            PipelineRun.trigger_root_event_id.is_(None) & (PipelineRun.trigger_event_id == root_id),
        ),
    ).scalar_subquery()
    duplicate_found, root_runs = (await db.execute(select(duplicate, count))).one()
    return duplicate_found, root_runs


async def trigger_root_available(db: AsyncSession, event: DeviceEvent, *, lock: bool = False) -> bool:
    root_id = event.trigger_root_event_id or event.id
    if lock and db.get_bind().dialect.name == "postgresql":
        # Unlike a row lock, this uses the same read-only table permissions as
        # simulation and is released on commit. The domain and tenant are part
        # of the key, so unrelated event streams do not serialize.
        key = int.from_bytes(hashlib.sha256(
            f"sphere:trigger-root:v1:{event.org_id}:{root_id}".encode()
        ).digest()[:8], "big", signed=True)
        await db.execute(select(func.pg_advisory_xact_lock(key)))
    if event.trigger_root_event_id is None:
        return True
    root = select(DeviceEvent.id).where(
        DeviceEvent.id == root_id,
        DeviceEvent.org_id == event.org_id,
        DeviceEvent.device_id == event.device_id,
    )
    return await db.scalar(root) is not None


async def simulate_trigger(
    db: AsyncSession, trigger: EventTrigger, event_type: str, event: DeviceEvent | None = None,
) -> EventTriggerSimulationResponse:
    active = await db.scalar(select(Pipeline.is_active).where(
        Pipeline.id == trigger.pipeline_id, Pipeline.org_id == trigger.org_id,
    ))
    root_available = event is None or await trigger_root_available(db, event)
    return await inspect_trigger(
        db, trigger, event_type, await trigger_clock(db), pipeline_active=bool(active),
        count_unlimited=True, event=event, root_available=root_available,
    )
