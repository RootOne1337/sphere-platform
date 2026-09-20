# backend/services/orchestrator/pipeline_executor.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Движок исполнения pipeline (фоновый loop).
#
# Цикл работы:
#   1. SELECT ... WHERE status = 'queued' ORDER BY created_at FOR UPDATE SKIP LOCKED
#   2. Переводим в RUNNING, исполняем шаги последовательно
#   3. Каждый шаг → StepHandler → результат → обновление context / step_logs
#   4. Финальный статус: COMPLETED / FAILED / TIMED_OUT
#
# Важно: executor работает с собственной DB-сессией (не endpoint).
from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import structlog
from sqlalchemy import select

from backend.database.engine import AsyncSessionLocal
from backend.models.pipeline import PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_ownership import database_now, scheduled_generation
from backend.services.orchestrator.pipeline_recovery import (
    LEASE_SECONDS,
    OwnedPipelineRunner,
    recover_expired,
)
from backend.services.orchestrator.step_handlers import (
    StepHandlerRegistry,  # noqa: F401 — public patch point
)

logger = structlog.get_logger()

# Интервал опроса очереди QUEUED runs
_POLL_INTERVAL_SECONDS = 2.0

# Максимум принятых runs на executor/process, не на весь кластер.
_MAX_CONCURRENT_RUNS = 10
_DRAIN_SECONDS = 30


class PipelineExecutor:
    """
    Фоновый движок исполнения pipeline.

    Поллит БД на наличие QUEUED pipeline_runs,
    берёт записи через FOR UPDATE SKIP LOCKED (безопасно для multi-instance),
    исполняет шаги, обновляет статусы.
    """

    def __init__(self) -> None:
        self._running = False
        self._owner = uuid.uuid4()
        self._stopping = False
        self._poll_lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT_RUNS)
        self._tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """Запуск фонового loop."""
        if self._running or self._stopping:
            raise RuntimeError("Use one loop per executor and a fresh instance after stop")
        self._running = True
        logger.info("pipeline_executor.started")
        while self._running:
            try:
                await self._poll_and_dispatch()
            except Exception as exc:
                logger.error("pipeline_executor.poll_error", error=str(exc))
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Остановка executor."""
        self._stopping = True
        self._running = False
        # Include a claim whose commit was already in flight when stop began.
        # A claim not yet committed observes the fence and rolls back instead.
        try:
            async with self._poll_lock:
                tasks = set(self._tasks)
            if tasks:
                await asyncio.wait(tasks, timeout=_DRAIN_SECONDS)
        finally:
            # Also reached when the application's outer shutdown deadline expires.
            pending = {task for task in self._tasks if not task.done()}
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=3)
            logger.info("pipeline_executor.admission_stopped",
                        pending_coroutines=sum(not task.done() for task in pending))

    async def _poll_and_dispatch(self) -> None:
        """Выбрать QUEUED runs и запустить в параллель (с ограничением _MAX_CONCURRENT_RUNS)."""
        # Reserve capacity across SELECT, commit and task registration. Otherwise
        # concurrent polls can both see the same free slots. Semaphore alone only
        # bounds execution, leaving an unbounded in-memory queue marked RUNNING.
        async with self._poll_lock:
            if self._stopping:
                return
            # Cancellation reconciliation must run even when every slot is busy.
            await self._reconcile_cancellations()
            await recover_expired(AsyncSessionLocal)
            available = _MAX_CONCURRENT_RUNS - len(self._tasks)
            if self._stopping or available <= 0:
                return
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(PipelineRun)
                    .where(PipelineRun.status == PipelineRunStatus.QUEUED)
                    .where(PipelineRun.cancel_requested_at.is_(None))
                    .order_by(PipelineRun.created_at, PipelineRun.id)
                    .limit(available)
                    .with_for_update(skip_locked=True)
                )
                runs = result.scalars().all()
                if self._stopping:
                    await db.rollback()
                    return
                now = await database_now(db)
                for run in runs:
                    run.status = PipelineRunStatus.RUNNING
                    run.started_at = run.started_at or now
                    run.execution_owner = self._owner
                    run.execution_generation += 1
                    run.execution_lease_until = now + timedelta(seconds=LEASE_SECONDS)
                await db.commit()

            # No await between registration operations: each task is a reserved
            # slot, including the short interval before its coroutine starts.
            for run in runs:
                task = asyncio.create_task(self._execute_run_safe(run.id, run.execution_generation))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _reconcile_cancellations(self, *, org_id: uuid.UUID | None = None) -> None:
        """Finish persisted cancellations after restart, without replaying a step."""
        from backend.services.orchestrator.pipeline_service import PipelineService

        async with AsyncSessionLocal() as db:
            query = select(PipelineRun.id, PipelineRun.org_id).where(
                PipelineRun.cancel_requested_at.is_not(None),
                PipelineRun.status.in_([PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                                       PipelineRunStatus.WAITING, PipelineRunStatus.PAUSED]),
            )
            if org_id is not None:
                query = query.where(PipelineRun.org_id == org_id)
            candidates = list((await db.execute(query.order_by(PipelineRun.updated_at, PipelineRun.id).limit(64))).all())
        for run_id, tenant_id in candidates:
            async with AsyncSessionLocal() as db:
                children = list(await db.scalars(select(PipelineRun.id).where(
                    PipelineRun.org_id == tenant_id,
                    PipelineRun.context["parent_run_id"].astext == str(run_id),
                    PipelineRun.status.in_([PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                                           PipelineRunStatus.WAITING, PipelineRunStatus.PAUSED]),
                )))
            # Separate transactions preserve Task -> Run lock ordering at every
            # depth; a parent's run lock is never held while acquiring its child.
            for child_id in children:
                async with AsyncSessionLocal() as db:
                    try:
                        await PipelineService(db).cancel_run(child_id, tenant_id)
                        await db.commit()
                    except Exception as exc:
                        await db.rollback()
                        logger.warning("pipeline.cancel.child_pending", run_id=str(child_id), error_type=type(exc).__name__)
            async with AsyncSessionLocal() as db:
                try:
                    await PipelineService(db).cancel_run(run_id, tenant_id)
                    await db.commit()
                except Exception as exc:
                    await db.rollback()
                    logger.warning("pipeline.cancel.reconcile_pending", run_id=str(run_id), error_type=type(exc).__name__)

    async def _execute_run_safe(self, run_id: uuid.UUID, generation: int | None = None) -> None:
        async with self._semaphore:
            token = scheduled_generation.set(generation)
            try:
                await self._execute_run(run_id)
            except Exception as exc:
                # Unknown SQL/handler outcomes remain recoverable. A stale owner
                # must never unconditionally overwrite another generation's state.
                logger.error("pipeline_executor.run_interrupted", run_id=str(run_id),
                             error_type=type(exc).__name__)
            finally:
                scheduled_generation.reset(token)

    async def _execute_run(self, run_id: uuid.UUID) -> None:
        await OwnedPipelineRunner(self._owner, AsyncSessionLocal, scheduled_generation.get()).run(run_id)
