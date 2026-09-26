"""A SQL-only wave and its cursor commit together; no replay after lost commit ACK.

The transaction advisory lock is the ownership fence. There are no network/device
effects in admission, and PostgreSQL releases it on worker death/rollback. Never
hold TaskBatch before Task/device: result handlers use the opposite lock order.
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import uuid
from datetime import timedelta

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select, text, update

from backend.database.tenant import bind_tenant_context
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.services.orchestrator.pipeline_ownership import database_now

logger = structlog.get_logger()
ACTIVE = (TaskBatchStatus.PENDING, TaskBatchStatus.RUNNING)
POLL_SECONDS = 1.0
MAX_BATCHES_PER_POLL = 32
WAVE_TIMEOUT_SECONDS = 15


def initialize_plan(batch: TaskBatch, waves: list[list[uuid.UUID]], version_id: uuid.UUID) -> None:
    """Only called before the initial commit. Existing plans are never rebuilt."""
    batch.wave_plan = [[{"device_id": str(device), "task_id": str(uuid.uuid5(batch.id, f"{w}:{i}"))}
                        for i, device in enumerate(wave)] for w, wave in enumerate(waves)]
    batch.script_version_id = version_id
    batch.next_wave_index = 0
    batch.admission_state = "pending" if waves else "submitted"
    batch.admission_receipts = []
    batch.next_wave_at = None


async def advance_batch(sessions, batch_id: uuid.UUID, org_id: uuid.UUID, *, skip_locked: bool = True) -> bool:
    """Admit at most one due wave. True means a committed cursor advance."""
    from backend.services.task_service import TaskService

    async with sessions() as db:
        await bind_tenant_context(db, str(org_id))
        key = int.from_bytes(hashlib.sha256(f"batch-production:{batch_id}".encode()).digest()[:8], "big", signed=True)
        if skip_locked:
            if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
                return False
        else:
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        batch = await db.scalar(select(TaskBatch).where(TaskBatch.id == batch_id, TaskBatch.org_id == org_id))
        now = await database_now(db)
        if (batch is None or batch.status not in ACTIVE or batch.admission_state != "pending"
                or (batch.next_wave_at is not None and batch.next_wave_at > now)):
            return False
        plan = batch.wave_plan
        cursor = batch.next_wave_index
        if not plan or not batch.script_version_id or cursor < 0 or cursor >= len(plan):
            await db.execute(update(TaskBatch).where(TaskBatch.id == batch.id).values(
                admission_state="review_required", next_wave_at=None))
            await db.commit()
            logger.error("batch.admission.invalid_plan", batch_id=str(batch_id))
            return False

        task_svc = TaskService(db)
        receipts = []
        failed = 0
        for item in sorted(plan[cursor], key=lambda value: value["device_id"]):
            device_id, task_id = uuid.UUID(item["device_id"]), uuid.UUID(item["task_id"])
            try:
                await task_svc.create_task(
                    script_id=batch.script_id, script_version_id=batch.script_version_id,
                    device_id=device_id, task_id=task_id, org_id=org_id,
                    priority=batch.wave_config.get("priority", 5), batch_id=batch_id, wave_index=cursor,
                )
                receipts.append({**item, "wave_index": cursor, "outcome": "admitted"})
            except HTTPException as exc:
                if not 400 <= exc.status_code < 500:
                    raise
                failed += 1
                # Do not copy exception detail; it can contain another task ID.
                receipts.append({**item, "wave_index": cursor, "outcome": "rejected", "http_status": exc.status_code})
        if failed:
            await task_svc._aggregate_batch(batch_id, success=False, count=failed)
        # No awaitable external operation before commit. Cursor, admission
        # receipts, rejection counters and new Tasks all share this transaction.
        done = cursor + 1 == len(plan)
        delay = batch.wave_config.get("wave_delay_ms", 0) + random.randint(0, batch.wave_config.get("jitter_ms", 0))
        now = await database_now(db)
        await db.execute(update(TaskBatch).where(TaskBatch.id == batch_id).values(
            next_wave_index=cursor + 1, admission_state="submitted" if done else "pending",
            next_wave_at=None if done else now + timedelta(milliseconds=delay),
            admission_receipts=[*(batch.admission_receipts or []), *receipts],
        ))
        await db.commit()
        logger.info("batch.wave.admitted", batch_id=str(batch_id), wave_index=cursor,
                    admitted=len(receipts) - failed, rejected=failed, all_submitted=done)
        return True


class BatchAdmissionWorker:
    """One loop per process; no unbounded per-batch tasks or sleeps with DB locks."""

    def __init__(self, sessions):
        self.sessions = sessions

    async def poll(self, *, org_id: uuid.UUID | None = None) -> None:
        async with self.sessions() as db:
            query = select(TaskBatch.id, TaskBatch.org_id).where(
                TaskBatch.status.in_(ACTIVE), TaskBatch.admission_state == "pending",
                (TaskBatch.next_wave_at.is_(None)) | (TaskBatch.next_wave_at <= func.clock_timestamp()),
            )
            if org_id is not None:
                await bind_tenant_context(db, str(org_id))
                query = query.where(TaskBatch.org_id == org_id)
                candidates = list((await db.execute(query.order_by(
                    TaskBatch.next_wave_at.asc().nullsfirst(), TaskBatch.created_at, TaskBatch.id,
                ).limit(MAX_BATCHES_PER_POLL))).all())
            else:
                # Narrow, explicitly granted lookup yields only due work IDs.
                # All subsequent reads/writes bind that item's tenant under RLS.
                candidates = list((await db.execute(text("SELECT * FROM sphere_auth.due_batch_admissions()"))).all())
        for batch_id, tenant in candidates:
            try:
                await asyncio.wait_for(advance_batch(self.sessions, batch_id, tenant), WAVE_TIMEOUT_SECONDS)
            except Exception as exc:
                logger.warning("batch.admission.retry_pending", batch_id=str(batch_id), error_type=type(exc).__name__)
                # A lost commit ACK may already have advanced the cursor. Only
                # defer another attempt; never infer or undo admission progress.
                try:
                    async with self.sessions() as db:
                        await bind_tenant_context(db, str(tenant))
                        await db.execute(update(TaskBatch).where(
                            TaskBatch.id == batch_id, TaskBatch.org_id == tenant,
                            TaskBatch.admission_state == "pending", TaskBatch.status.in_(ACTIVE),
                        ).values(next_wave_at=func.greatest(
                            TaskBatch.next_wave_at, func.clock_timestamp() + timedelta(seconds=5),
                        )))
                        await db.commit()
                except Exception:
                    logger.warning("batch.admission.retry_defer_failed", batch_id=str(batch_id))

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
            except Exception as exc:
                logger.warning("batch.admission.poll_failed", error_type=type(exc).__name__)
            await asyncio.sleep(POLL_SECONDS)
