# backend/services/batch_service.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Wave Batch Execution — волновой запуск на флите.
#
# Архитектурные особенности:
#   — start_batch() возвращает 202 немедленно, волны запускаются в фоне
#   — FIX-4.1: фоновая задача использует ИЗОЛИРОВАННУЮ сессию (не DI-сессию)
#   — FIX-4.3: глобальный set _background_tasks защищает задачи от GC
#   — Завершение волн означает создание intent, а не выполнение на устройстве
#   — Частичный прогресс сохраняется (коммит каждой волны отдельно)
from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.script import Script
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.schemas.batch import BatchExecutionRequest, BroadcastBatchRequest
from backend.services.workstation_mapping import WorkstationMappingService

logger = structlog.get_logger()

# FIX-4.3: Глобальный set фоновых задач — переживает HTTP-запрос, защита от GC
_background_tasks: set[asyncio.Task] = set()


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
        """Prepare and commit the batch before starting independent wave work.

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

        # Создать batch-запись (в рамках текущей DI-сессии — запрос ещё жив)
        batch = TaskBatch(
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
        self.db.add(batch)
        await self.db.flush()
        batch_id = batch.id

        # Разбить на волны
        mapping_svc = WorkstationMappingService(self.db)
        waves = await mapping_svc.create_waves(
            device_ids=request.device_ids,
            org_id=org_id,
            wave_size=request.wave_size,
            stagger_by_workstation=request.stagger_by_workstation,
        )

        # The worker must never race an uncommitted parent or escape a failed
        # commit. A process crash between commit and launch still needs durable
        # wave-plan recovery; moving task creation earlier cannot solve that.
        await self.db.commit()

        # FIX-4.3: Запустить фоновую задачу, защитить от GC через глобальный set
        bg_task = asyncio.create_task(
            self._execute_waves(batch_id, waves, request, org_id),
            name=f"batch_waves_{batch_id}",
        )
        _background_tasks.add(bg_task)
        bg_task.add_done_callback(_background_tasks.discard)

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

    async def _execute_waves(
        self,
        batch_id: uuid.UUID,
        waves: list[list[uuid.UUID]],
        request: BatchExecutionRequest,
        org_id: uuid.UUID,
    ) -> None:
        """
        FIX-4.1: Фоновая задача с ИЗОЛИРОВАННОЙ сессией.
        DI-сессия self.db уже закрыта к этому моменту!
        """
        async with self._session_maker() as db:
            from backend.database.redis_client import redis as _redis
            from backend.services.task_queue import TaskQueue
            from backend.services.task_service import TaskService

            queue = TaskQueue(_redis)
            task_svc = TaskService(db, queue)

            for wave_num, wave_devices in enumerate(waves):
                failed = 0
                logger.info(
                    "batch.wave.start",
                    batch_id=str(batch_id),
                    wave=f"{wave_num + 1}/{len(waves)}",
                    devices=len(wave_devices),
                )

                for device_id in wave_devices:
                    try:
                        await task_svc.create_task(
                            script_id=request.script_id,
                            device_id=device_id,
                            org_id=org_id,
                            priority=request.priority,
                            webhook_url=None,   # webhook только для батча в целом
                            batch_id=batch_id,
                            wave_index=wave_num,
                        )
                    except HTTPException as exc:
                        if not 400 <= exc.status_code < 500:
                            raise
                        logger.warning(
                            "batch.wave.task_create_failed",
                            device_id=str(device_id),
                            error=str(exc),
                        )
                        failed += 1

                # Admission rejections are terminal failures for requested slots.
                # Account for them under the same row lock as device results,
                # after all task/device locks, in this wave's transaction.
                if failed:
                    await task_svc._aggregate_batch(batch_id, success=False, count=failed)

                # Коммит каждой волны — частичный прогресс сохраняется
                await db.commit()

                # Ждать задержку между волнами с jitter (кроме последней волны)
                if wave_num < len(waves) - 1:
                    jitter = random.randint(0, request.jitter_ms)
                    delay_s = (request.wave_delay_ms + jitter) / 1000
                    await asyncio.sleep(delay_s)

        # SQL admission is not completion. Task results/watchdogs determine the
        # final state. A completion webhook requires a post-commit outcome outbox;
        # never announce success merely because all waves have been submitted.
        logger.info(
            "batch.waves_submitted",
            batch_id=str(batch_id),
            waves=len(waves),
        )

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
        Отменяет QUEUED/ASSIGNED задачи; RUNNING завершаются самостоятельно.
        ASSIGNED может быть в доставке: SQL отмена не доказывает остановку APK.
        """
        batch = await self.get_batch(batch_id, org_id)

        if batch.status not in (TaskBatchStatus.PENDING, TaskBatchStatus.RUNNING):
            raise HTTPException(
                status_code=409,
                detail=f"Batch already in terminal status '{batch.status}'",
            )

        # Result handlers acquire Task -> TaskBatch. Keep the same order and
        # deterministic task ordering so cancellation cannot invert those locks.
        from backend.database.redis_client import redis as _redis
        from backend.services.task_queue import TaskQueue

        queue = TaskQueue(_redis)
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
        now = datetime.now(timezone.utc)
        for task in queued_tasks:
            await queue.cancel_task(str(task.id), str(org_id), str(task.device_id))
            task.status = TaskStatus.CANCELLED
            task.finished_at = now

        batch.status = TaskBatchStatus.CANCELLED
        logger.info("batch.cancelled", batch_id=str(batch_id), tasks_cancelled=len(queued_tasks))
