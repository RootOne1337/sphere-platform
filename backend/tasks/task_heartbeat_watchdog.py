"""Persist stop intent for overdue delivered work; expire only undelivered tasks.

ASSIGNED/RUNNING stays active until an APK terminal receipt. Task dispatcher
redelivers durable cancellation independently of this worker and Redis recovery.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, or_, select, text

from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.database.engine import AsyncSessionLocal
from backend.database.tenant import bind_tenant_context

logger = structlog.get_logger()

# ── Конфигурация ─────────────────────────────────────────────────────────────

# Дополнительный буфер (сек) сверх task.timeout_seconds для RUNNING задач.
# task.timeout_seconds=300 (5 мин) → stale threshold = 300+300 = 600с (10 мин).
# Задачи планировщика (перезапуск скрипта) должны укладываться в <5 мин — 10 мин запас.
_STALE_BUFFER_SECONDS: int = int(os.environ.get("TASK_STALE_BUFFER_SECONDS", "300"))

# Абсолютный таймаут для QUEUED/ASSIGNED задач без started_at.
# QUEUED expires locally; ASSIGNED and missing-start RUNNING require an APK stop receipt.
_QUEUED_STALE_MINUTES: int = int(os.environ.get("TASK_QUEUED_STALE_MINUTES", "60"))

# Интервал watchdog цикла в секундах.
_WATCHDOG_INTERVAL_SECONDS: int = 60

# Ссылка на asyncio.Task — защита от garbage collector.
_watchdog_task: asyncio.Task | None = None


# ── Основная логика ──────────────────────────────────────────────────────────

_PAGE_SIZE = 64
_DISCOVERY_TIMEOUT_SECONDS = 5.0
_TASK_TIMEOUT_SECONDS = 10.0
_CONCURRENCY = 4
_watchdog_cursor: uuid.UUID | None = None


async def _process_stale_tasks(
    db,
    *,
    stale_buffer_seconds: int,
    queued_stale_minutes: int,
    use_for_update: bool = True,
    org_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """Caller owns commit. Return requested stops and locally expired QUEUED IDs.

    No Redis/network effects. Only never-dispatched QUEUED work is terminal here;
    delivered work retains its status/device fence until an APK terminal receipt.
    """
    from backend.models.task import Task, TaskStatus
    from backend.models.task_batch import TaskBatch, TaskBatchStatus

    if stale_buffer_seconds < 0 or queued_stale_minutes < 0:
        raise ValueError("Watchdog deadlines must be nonnegative")
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=queued_stale_minutes)
    query = select(Task).where(
        Task.status.in_([TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING]),
        Task.cancel_requested_at.is_(None),
        *([Task.org_id == org_id] if org_id is not None else []),
        *([Task.id == task_id] if task_id is not None else []),
    )
    if use_for_update:
        # PostgreSQL filters before LIMIT/lock; healthy work cannot hide due rows.
        query = query.where(or_(
            and_(Task.status == TaskStatus.RUNNING, Task.started_at.is_not(None),
                 Task.started_at + (Task.timeout_seconds + stale_buffer_seconds)*timedelta(seconds=1) <= now),
            and_(or_(Task.status.in_([TaskStatus.QUEUED, TaskStatus.ASSIGNED]), Task.started_at.is_(None)),
                 Task.created_at < cutoff),
        )).order_by(Task.id).limit(_PAGE_SIZE).with_for_update(skip_locked=True)
    rows = list(await db.scalars(query.execution_options(populate_existing=True)))
    stops: list[tuple[str, str]] = []
    expired: list[tuple[str, str, str]] = []
    timed = []
    for task in rows:
        # Also preserve the SQLite test path's timezone/deadline semantics.
        anchor = task.started_at if task.status == TaskStatus.RUNNING and task.started_at is not None else task.created_at
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        due = (anchor + timedelta(seconds=task.timeout_seconds + stale_buffer_seconds) <= now
               if task.status == TaskStatus.RUNNING and task.started_at is not None else anchor < cutoff)
        if not due:
            continue
        task.timeout_requested_at = now
        if task.status == TaskStatus.QUEUED:
            task.status = TaskStatus.TIMEOUT
            task.finished_at = now
            task.error_message = f"Watchdog: undispatched task exceeded {queued_stale_minutes} minute queue deadline"
            expired.append((str(task.id), str(task.device_id), str(task.org_id)))
            timed.append(task)
        else:
            # Same durable target/late-command fence as user cancellation. Do not
            # aggregate a batch or release execution before physical outcome.
            task.cancel_requested_at = now
            task.error_message = "Watchdog: deadline exceeded; waiting for terminal device receipt"
            stops.append((str(task.id), str(task.device_id)))
    if timed:
        await _aggregate_batches(db, timed, now, TaskBatch, TaskBatchStatus)
    return stops, expired


async def _discover_stale_tasks(after_task: uuid.UUID | None) -> list[tuple[uuid.UUID, uuid.UUID]]:
    async with asyncio.timeout(_DISCOVERY_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
        query = text("SELECT * FROM sphere_auth.watchdog_work(:stale, :queued, :after)")
        params = {"stale": _STALE_BUFFER_SECONDS, "queued": _QUEUED_STALE_MINUTES, "after": after_task}
        rows = list((await db.execute(query, params)).all())
        if not rows and after_task is not None:
            rows = list((await db.execute(query, {**params, "after": None})).all())
    return [(row[0], row[1]) for row in rows]


async def _expire_stale_tasks() -> None:
    """Bounded UUID discovery then scoped, atomic timeout intent; no live sends."""
    global _watchdog_cursor
    candidates = await _discover_stale_tasks(_watchdog_cursor)

    async def process(task_id: uuid.UUID, tenant: uuid.UUID) -> None:
        try:
            async with asyncio.timeout(_TASK_TIMEOUT_SECONDS), AsyncSessionLocal() as db:
                await bind_tenant_context(db, str(tenant))
                stops, expired = await _process_stale_tasks(
                    db, stale_buffer_seconds=_STALE_BUFFER_SECONDS,
                    queued_stale_minutes=_QUEUED_STALE_MINUTES, org_id=tenant, task_id=task_id,
                )
                await db.commit()
                if stops or expired:
                    logger.info("task.watchdog.intent_committed", task_id=str(task_id),
                                stop_requested=bool(stops), expired_undispatched=bool(expired))
        except Exception as exc:
            # Session exit rolls back. An uncertain commit is reconciled from SQL
            # on the next tick; no external effect is replayed in this worker.
            logger.warning("task.watchdog.retry_pending", task_id=str(task_id), error_type=type(exc).__name__)

    for offset in range(0, len(candidates), _CONCURRENCY):
        await asyncio.gather(*(process(*item) for item in candidates[offset:offset + _CONCURRENCY]))
    _watchdog_cursor = candidates[-1][0] if len(candidates) == _PAGE_SIZE else None


async def _aggregate_batches(
    db,
    timed_tasks,
    now: datetime,
    TaskBatch,
    TaskBatchStatus,
) -> None:
    """
    Инкрементально обновить счётчики TaskBatch для тайм-аутовавших задач.

    Группируем по batch_id, считаем количество TIMEOUT-задач в каждом batch
    и обновляем batch.failed. Если все задачи batch завершены — вычисляем
    финальный статус (FAILED / COMPLETED / PARTIAL).
    """
    # Собираем уникальные batch_id
    batch_ids_counts: dict = {}  # batch_id → count of timed-out tasks
    for task in timed_tasks:
        if task.batch_id:
            batch_ids_counts[task.batch_id] = batch_ids_counts.get(task.batch_id, 0) + 1

    # Use the same lock as TaskService result accounting and a stable acquisition
    # order when a watchdog transaction touches more than one batch.
    for batch_id, timeout_count in sorted(batch_ids_counts.items()):
        batch = await db.scalar(select(TaskBatch).where(
            TaskBatch.id == batch_id,
        ).with_for_update().execution_options(populate_existing=True))
        if not batch:
            continue

        batch.failed = (batch.failed or 0) + timeout_count
        completed_count = (batch.succeeded or 0) + (batch.failed or 0)

        # A timeout is an outcome of surviving work, not a reason to reopen a
        # batch whose remaining admission was cancelled.
        if completed_count >= batch.total and batch.status != TaskBatchStatus.CANCELLED:
            if (batch.failed or 0) == 0:
                batch.status = TaskBatchStatus.COMPLETED
            elif (batch.succeeded or 0) == 0:
                batch.status = TaskBatchStatus.FAILED
            else:
                batch.status = TaskBatchStatus.PARTIAL

            logger.info(
                "task.watchdog.batch_finalized",
                batch_id=str(batch_id),
                status=batch.status,
                succeeded=batch.succeeded,
                failed=batch.failed,
                total=batch.total,
            )


# ── Watchdog loop ────────────────────────────────────────────────────────────

async def _watchdog_loop() -> None:
    """Бесконечный цикл watchdog с паузой _WATCHDOG_INTERVAL_SECONDS."""
    logger.info(
        "task_heartbeat_watchdog.started",
        interval_s=_WATCHDOG_INTERVAL_SECONDS,
        stale_buffer_s=_STALE_BUFFER_SECONDS,
        queued_stale_m=_QUEUED_STALE_MINUTES,
    )
    while True:
        try:
            await _expire_stale_tasks()
        except Exception as exc:
            logger.error(
                "task_heartbeat_watchdog.unhandled_error",
                error=str(exc),
                exc_info=True,
            )
        await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)


# ── Авторегистрация через lifespan_registry ──────────────────────────────────

async def _startup() -> None:
    """Запуск watchdog при старте FastAPI."""
    global _watchdog_task
    _watchdog_task = asyncio.create_task(
        _watchdog_loop(),
        name="task_heartbeat_watchdog",
    )
    logger.info(
        "task_heartbeat_watchdog.registered",
        stale_buffer_s=_STALE_BUFFER_SECONDS,
        queued_stale_m=_QUEUED_STALE_MINUTES,
    )


async def _shutdown() -> None:
    """Graceful shutdown watchdog при остановке FastAPI."""
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass
    logger.info("task_heartbeat_watchdog.stopped")


register_startup("task_heartbeat_watchdog", _startup)
register_shutdown("task_heartbeat_watchdog", _shutdown)
