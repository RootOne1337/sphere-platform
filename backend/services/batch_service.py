# backend/services/batch_service.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Wave Batch Execution — волновой запуск на флите.
#
# Архитектурные особенности:
#   — start_batch() сохраняет план до HTTP 202
#   — startup worker восстанавливает волны из SQL, без coroutine на каждый batch
#   — Завершение волн означает создание intent, а не выполнение на устройстве
#   — Частичный прогресс сохраняется (коммит каждой волны отдельно)
from __future__ import annotations

import hashlib
import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.script import Script
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.schemas.batch import BatchExecutionRequest, BroadcastBatchRequest
from backend.services.workstation_mapping import WorkstationMappingService

logger = structlog.get_logger()

async def _lock_batch_production(db: AsyncSession, batch_id: uuid.UUID) -> None:
    """Fence wave admission and cancellation, even when no Task row exists yet.

    This transaction lock precedes task/device locks. Do not lock TaskBatch
    before Task: result handlers already use Task -> TaskBatch ordering.
    """
    key = int.from_bytes(hashlib.sha256(f"batch-production:{batch_id}".encode()).digest()[:8],
                         "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


class BatchService:
    def __init__(
        self,
        db: AsyncSession,
        session_maker: async_sessionmaker,
    ) -> None:
        self.db = db
        # FIX-4.1: сохраняем фабрику сессий, а не DI-сессию
        self._session_maker = session_maker

    async def start_batch(
        self,
        request: BatchExecutionRequest,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> TaskBatch:
        """Persist the full plan before returning; startup workers admit due waves.

        This entry point owns its transaction boundary because its worker uses
        a different session. A successful return is already durable.
        """
        # Проверить скрипт
        script = await self.db.scalar(
            select(Script).where(
                Script.id == request.script_id,
                Script.org_id == org_id,
                Script.is_archived.is_(False),
            )
        )
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        if not script.current_version_id:
            raise HTTPException(status_code=400, detail="Script has no versions")

        mapping_svc = WorkstationMappingService(self.db)
        waves = await mapping_svc.create_waves(
            device_ids=request.device_ids, org_id=org_id, wave_size=request.wave_size,
            stagger_by_workstation=request.stagger_by_workstation,
        )

        # Создать batch-запись (в рамках текущей DI-сессии — запрос ещё жив)
        batch = TaskBatch(
            id=uuid.uuid4(),
            org_id=org_id,
            script_id=request.script_id,
            name=request.name,
            status=TaskBatchStatus.RUNNING,
            total=len(request.device_ids),
            wave_config={
                "wave_size": request.wave_size,
                "wave_delay_ms": request.wave_delay_ms,
                "jitter_ms": request.jitter_ms,
                "priority": request.priority,
                "stagger_by_workstation": request.stagger_by_workstation,
                "webhook_url": request.webhook_url,
            },
            created_by_id=user_id,
        )
        from backend.services.batch_admission import initialize_plan

        initialize_plan(batch, waves, script.current_version_id)
        self.db.add(batch)
        await self.db.flush()
        # Plan and fixed version are durable before HTTP 202. The bounded
        # startup worker discovers intent even if this process dies right here.
        await self.db.commit()

        return batch

    async def broadcast_batch(
        self,
        request: BroadcastBatchRequest,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> tuple[TaskBatch, int]:
        """
        Запуск скрипта на ВСЕХ онлайн-устройствах организации.

        1. Получаем все device_id организации из БД
        2. Фильтруем через status_cache — оставляем только online
        3. Делегируем start_batch() с подготовленным списком

        Возвращает (batch, online_count).
        """
        from backend.database.redis_client import redis as _redis
        from backend.services.cache_service import CacheService
        from backend.services.device_service import DeviceService
        from backend.services.device_status_cache import DeviceStatusCache

        # 1. Все активные устройства организации
        device_svc = DeviceService(self.db, CacheService())
        all_ids = await device_svc.get_all_device_ids(org_id)
        if not all_ids:
            raise HTTPException(
                status_code=404,
                detail="В организации нет активных устройств",
            )

        # 2. Фильтрация по live-статусу — только online
        status_cache = DeviceStatusCache(_redis)
        statuses = await status_cache.bulk_get_status(all_ids)
        online_ids = [
            uuid.UUID(did)
            for did, st in statuses.items()
            if st and st.status == "online"
        ]
        if not online_ids:
            raise HTTPException(
                status_code=409,
                detail="Нет онлайн-устройств для запуска",
            )

        logger.info(
            "broadcast.resolve",
            org_id=str(org_id),
            total_devices=len(all_ids),
            online_devices=len(online_ids),
        )

        # 3. Создаём стандартный BatchExecutionRequest и делегируем start_batch
        batch_request = BatchExecutionRequest(
            script_id=request.script_id,
            device_ids=online_ids,
            wave_size=request.wave_size,
            wave_delay_ms=request.wave_delay_ms,
            jitter_ms=request.jitter_ms,
            priority=request.priority,
            webhook_url=request.webhook_url,
            stagger_by_workstation=request.stagger_by_workstation,
            name=request.name or "Broadcast: все онлайн-устройства",
        )
        batch = await self.start_batch(batch_request, org_id, user_id)
        return batch, len(online_ids)

    async def _send_batch_complete_webhook(
        self,
        batch_id: uuid.UUID,
        url: str,
        succeeded: int,
        failed: int,
    ) -> None:
        from backend.services.webhook_service import WebhookService

        wh = WebhookService()
        await wh.deliver(
            url,
            {
                "event_type": "batch.completed",
                "batch_id": str(batch_id),
                "succeeded": succeeded,
                "failed": failed,
            },
        )

    async def get_batch(
        self, batch_id: uuid.UUID, org_id: uuid.UUID, *, for_update: bool = False
    ) -> TaskBatch:
        statement = select(TaskBatch).where(
            TaskBatch.id == batch_id,
            TaskBatch.org_id == org_id,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        batch = await self.db.scalar(statement)
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch

    async def cancel_batch(
        self, batch_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        """
        Cancels never-dispatched work and records durable stops for ASSIGNED.
        Already RUNNING tasks retain this endpoint's finish-current-work policy.
        """
        batch = await self.get_batch(batch_id, org_id)
        from backend.services.task_service import TaskService

        if batch.status not in (TaskBatchStatus.PENDING, TaskBatchStatus.RUNNING):
            raise HTTPException(
                status_code=409,
                detail=f"Batch already in terminal status '{batch.status}'",
            )

        # A task-only SELECT cannot see an in-flight wave's uncommitted inserts.
        # Wait for admission first so the subsequent query includes its commit.
        await _lock_batch_production(self.db, batch_id)

        # Result handlers acquire Task -> TaskBatch. Keep the same order and
        # deterministic task ordering so cancellation cannot invert those locks.
        queued_tasks = list(
            (
                await self.db.execute(
                    select(Task).where(
                        Task.batch_id == batch_id,
                        Task.org_id == org_id,
                        Task.status.in_([TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
                    ).order_by(Task.id).with_for_update().execution_options(populate_existing=True)
                )
            ).scalars().all()
        )
        # A result/cancellation may have committed while we waited for tasks.
        # Refresh any identity-map snapshot before validating or touching Redis.
        batch = await self.get_batch(batch_id, org_id, for_update=True)
        if batch.status not in (TaskBatchStatus.PENDING, TaskBatchStatus.RUNNING):
            raise HTTPException(
                status_code=409,
                detail=f"Batch already in terminal status '{batch.status}'",
            )
        for task in queued_tasks:
            await TaskService(self.db)._request_cancellation(task)

        batch.status = TaskBatchStatus.CANCELLED
        batch.admission_state = "cancelled"
        batch.next_wave_at = None
        logger.info("batch.cancelled", batch_id=str(batch_id), tasks_cancelled=len(queued_tasks))
