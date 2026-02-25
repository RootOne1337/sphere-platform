# backend/services/batch_service.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Wave Batch Execution — волновой запуск на флите.
#
# Архитектурные особенности:
#   — start_batch() возвращает 202 немедленно, волны запускаются в фоне
#   — FIX-4.1: фоновая задача использует ИЗОЛИРОВАННУЮ сессию (не DI-сессию)
#   — FIX-4.3: глобальный set _background_tasks защищает задачи от GC
#   — FIX-4.2: статус батча обновляется С КОММИТОМ после завершения волн
#   — Частичный прогресс сохраняется (коммит каждой волны отдельно)
from __future__ import annotations

import asyncio
import random
import uuid

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.script import Script
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.schemas.batch import BatchExecutionRequest
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

        # FIX-4.3: Запустить фоновую задачу, защитить от GC через глобальный set
        bg_task = asyncio.create_task(
            self._execute_waves(batch_id, waves, request, org_id),
            name=f"batch_waves_{batch_id}",
        )
        _background_tasks.add(bg_task)
        bg_task.add_done_callback(_background_tasks.discard)

        return batch

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
        succeeded = 0
        failed = 0

        async with self._session_maker() as db:
            from backend.database.redis_client import redis as _redis
            from backend.services.task_queue import TaskQueue
            from backend.services.task_service import TaskService

            queue = TaskQueue(_redis)
            task_svc = TaskService(db, queue)

            for wave_num, wave_devices in enumerate(waves):
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
                    except Exception as exc:
                        logger.warning(
                            "batch.wave.task_create_failed",
                            device_id=str(device_id),
                            error=str(exc),
                        )
                        failed += 1

                # Коммит каждой волны — частичный прогресс сохраняется
                await db.commit()

                # Ждать задержку между волнами с jitter (кроме последней волны)
                if wave_num < len(waves) - 1:
                    jitter = random.randint(0, request.jitter_ms)
                    delay_s = (request.wave_delay_ms + jitter) / 1000
                    await asyncio.sleep(delay_s)

        # FIX-4.2: Обновить статус батча С КОММИТОМ — без этого статус зависнет в RUNNING
        async with self._session_maker() as db:
            batch = await db.get(TaskBatch, batch_id)
            if batch:
                batch.status = TaskBatchStatus.COMPLETED
                await db.commit()

        # Финальный webhook
        webhook_url = request.webhook_url
        if webhook_url:
            await self._send_batch_complete_webhook(
                batch_id, webhook_url, succeeded, failed
            )
        logger.info(
            "batch.completed",
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
        self, batch_id: uuid.UUID, org_id: uuid.UUID
    ) -> TaskBatch:
        batch = await self.db.scalar(
            select(TaskBatch).where(
                TaskBatch.id == batch_id,
                TaskBatch.org_id == org_id,
            )
        )
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        return batch

    async def cancel_batch(
        self, batch_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        """
        Отменяет батч: помечает незапущенные задачи CANCELLED.
        Уже запущенные задачи завершатся сами.
        """
        batch = await self.get_batch(batch_id, org_id)

        if batch.status in (TaskBatchStatus.COMPLETED, TaskBatchStatus.CANCELLED):
            raise HTTPException(
                status_code=409,
                detail=f"Batch already in terminal status '{batch.status}'",
            )

        # Отменить QUEUED задачи этого батча
        from backend.database.redis_client import redis as _redis
        from backend.services.task_queue import TaskQueue

        queue = TaskQueue(_redis)
        queued_tasks = list(
            (
                await self.db.execute(
                    select(Task).where(
                        Task.batch_id == batch_id,
                        Task.status.in_([TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
                    )
                )
            ).scalars().all()
        )
        for task in queued_tasks:
            await queue.cancel_task(str(task.id), str(org_id))
            task.status = TaskStatus.CANCELLED

        batch.status = TaskBatchStatus.CANCELLED
        logger.info("batch.cancelled", batch_id=str(batch_id), tasks_cancelled=len(queued_tasks))
