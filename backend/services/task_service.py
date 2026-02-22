# backend/services/task_service.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-3. Task lifecycle: создание, диспетчеризация, завершение.
#
# Lifecycle статусов:
#   QUEUED → RUNNING → COMPLETED | FAILED | TIMEOUT | CANCELLED
#
# Адаптации к реальной модели Task (TZ-00):
#   — status: QUEUED (не PENDING)
#   — finished_at (не completed_at)
#   — error_message (не error_msg)
#   — webhook_url хранится в input_params["webhook_url"]
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.services.task_queue import TaskQueue

logger = structlog.get_logger()

# Глобальный set для фоновых webhook-задач — защита от GC (HIGH-5)
_pending_webhook_tasks: set[asyncio.Task] = set()


class TaskService:
    def __init__(
        self,
        db: AsyncSession,
        queue: TaskQueue,
        status_cache: Any | None = None,
        publisher: Any | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.status_cache = status_cache
        self.publisher = publisher

    # ── Вспомогательные ─────────────────────────────────────────────────────

    async def _get_script(
        self, script_id: uuid.UUID, org_id: uuid.UUID
    ) -> Script:
        script = await self.db.scalar(
            select(Script).where(
                Script.id == script_id,
                Script.org_id == org_id,
                Script.is_archived.is_(False),
            )
        )
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        return script

    async def _get_device(
        self, device_id: uuid.UUID, org_id: uuid.UUID
    ) -> Device:
        device = await self.db.scalar(
            select(Device).where(
                Device.id == device_id,
                Device.org_id == org_id,
                Device.is_active.is_(True),
            )
        )
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return device

    async def _get_task(
        self, task_id: uuid.UUID, org_id: uuid.UUID
    ) -> Task:
        task = await self.db.scalar(
            select(Task).where(Task.id == task_id, Task.org_id == org_id)
        )
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_task(
        self,
        script_id: uuid.UUID,
        device_id: uuid.UUID,
        org_id: uuid.UUID,
        priority: int = 5,
        webhook_url: str | None = None,
        batch_id: uuid.UUID | None = None,
        wave_index: int | None = None,
    ) -> Task:
        script = await self._get_script(script_id, org_id)
        if not script.current_version_id:
            raise HTTPException(status_code=400, detail="Script has no versions")

        await self._get_device(device_id, org_id)

        # Идемпотентность: защита от дублирующих вызовов
        duplicate = await self.db.scalar(
            select(Task.id).where(
                Task.device_id == device_id,
                Task.org_id == org_id,
                Task.script_version_id == script.current_version_id,
                Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.ASSIGNED]),
            ).limit(1)
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"Task already queued/running for device (task_id={duplicate})",
            )

        input_params: dict = {"priority": priority}
        if webhook_url:
            input_params["webhook_url"] = webhook_url

        task = Task(
            org_id=org_id,
            script_id=script_id,
            script_version_id=script.current_version_id,
            device_id=device_id,
            priority=priority,
            input_params=input_params,
            batch_id=batch_id,
            wave_index=wave_index,
        )
        self.db.add(task)
        await self.db.flush()

        # Добавить в Redis очередь
        await self.queue.enqueue(
            str(task.id), str(device_id), str(org_id), priority
        )
        logger.info(
            "task.created",
            task_id=str(task.id),
            device_id=str(device_id),
            priority=priority,
        )
        return task

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def dispatch_pending_tasks(self) -> None:
        """
        Раздать задачи из очереди онлайн-агентам.
        Запускается периодически из _task_dispatcher_loop (регистрируется при старте).
        """
        if not self.status_cache:
            return

        online_device_ids = await self.status_cache.get_all_tracked_device_ids()

        for device_id_str in online_device_ids:
            # Получить org_id из Redis meta (если доступно) или брать из БД
            # Упрощённая версия: итерируем по всем устройствам из кэша
            try:
                device_uuid = uuid.UUID(device_id_str)
            except ValueError:
                continue

            device = await self.db.scalar(
                select(Device).where(Device.id == device_uuid, Device.is_active.is_(True))
            )
            if not device:
                continue

            task_id_str = await self.queue.dequeue_for_device(
                device_id_str, str(device.org_id)
            )
            if not task_id_str:
                continue

            try:
                task = await self.db.get(Task, uuid.UUID(task_id_str))
                if not task:
                    continue

                version = await self.db.get(ScriptVersion, task.script_version_id)
                if not version:
                    # version пропала — вернуть в очередь невозможно, помечаем failed
                    task.status = TaskStatus.FAILED
                    task.error_message = "Script version not found"
                    continue

                sent = False
                if self.publisher:
                    sent = await self.publisher.send_command_to_device(
                        device_id_str,
                        {
                            "type": "execute_dag",
                            "task_id": task_id_str,
                            "dag": version.dag,
                            "timeout_ms": task.timeout_seconds * 1000,
                        },
                    )

                if sent:
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now(timezone.utc)
                    logger.info("task.dispatched", task_id=task_id_str, device_id=device_id_str)
                else:
                    # Агент оффлайн — вернуть в очередь
                    await self.queue.enqueue(
                        task_id_str,
                        device_id_str,
                        str(device.org_id),
                        task.priority,
                    )
                    logger.warning(
                        "task.requeued.agent_offline",
                        task_id=task_id_str,
                        device_id=device_id_str,
                    )

            except Exception as exc:
                logger.error(
                    "task.dispatch_error",
                    task_id=task_id_str,
                    error=str(exc),
                    exc_info=True,
                )

    # ── Result handling ──────────────────────────────────────────────────────

    async def handle_task_result(
        self,
        task_id: str,
        device_id: str,
        result: dict,
    ) -> None:
        """Вызывается при получении command_result от агента (TZ-03 WebSocket)."""
        task = await self.db.get(Task, uuid.UUID(task_id))
        if not task:
            logger.warning("task.result.not_found", task_id=task_id)
            return

        success = result.get("success", False)
        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.finished_at = datetime.now(timezone.utc)
        task.result = result
        task.error_message = result.get("error")

        await self.queue.mark_completed(task_id, device_id)
        logger.info(
            "task.completed",
            task_id=task_id,
            success=success,
            device_id=device_id,
        )

        # Webhook callback (асинхронно — не блокирует)
        webhook_url = task.input_params.get("webhook_url") if task.input_params else None
        if webhook_url:
            from backend.services.webhook_service import WebhookService
            wh = WebhookService()
            _t = asyncio.create_task(
                wh.deliver(
                    webhook_url,
                    {
                        "event_type": "task.completed",
                        "task_id": task_id,
                        "device_id": device_id,
                        "success": success,
                        "result": result,
                    },
                )
            )
            # HIGH-5: глобальный set — GC не удалит задачу до завершения
            _pending_webhook_tasks.add(_t)
            _t.add_done_callback(_pending_webhook_tasks.discard)

    # ── Cancel ───────────────────────────────────────────────────────────────

    async def cancel_task(
        self, task_id: uuid.UUID, org_id: uuid.UUID
    ) -> Task:
        task = await self._get_task(task_id, org_id)

        if task.status not in (TaskStatus.QUEUED, TaskStatus.ASSIGNED):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel task in status '{task.status}'",
            )

        removed = await self.queue.cancel_task(str(task_id), str(org_id))
        task.status = TaskStatus.CANCELLED
        task.finished_at = datetime.now(timezone.utc)

        logger.info(
            "task.cancelled",
            task_id=str(task_id),
            was_in_queue=removed,
        )
        return task

    # ── Query ─────────────────────────────────────────────────────────────────

    async def list_tasks(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID | None = None,
        script_id: uuid.UUID | None = None,
        status: TaskStatus | None = None,
        batch_id: uuid.UUID | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Task], int]:
        from sqlalchemy import func

        stmt = select(Task).where(Task.org_id == org_id)

        if device_id:
            stmt = stmt.where(Task.device_id == device_id)
        if script_id:
            stmt = stmt.where(Task.script_id == script_id)
        if status:
            stmt = stmt.where(Task.status == status)
        if batch_id:
            stmt = stmt.where(Task.batch_id == batch_id)

        count = (
            await self.db.scalar(
                select(func.count()).select_from(stmt.subquery())
            )
        ) or 0

        items = list(
            (
                await self.db.execute(
                    stmt.order_by(Task.created_at.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            ).scalars().all()
        )
        return items, count


# ── Dispatcher loop (ARCH-3) ─────────────────────────────────────────────────
# Запускается один раз при старте через register_startup (см. tasks/router.py).
# Периодически раздаёт задачи из Redis очереди онлайн-агентам.

_dispatcher_task: asyncio.Task | None = None   # global ref — защита от GC


async def _task_dispatcher_loop(get_service_fn) -> None:
    """Цикл диспетчеризации. get_service_fn() создаёт TaskService с новой сессией."""
    logger.info("task_dispatcher.started", interval_s=5)
    while True:
        try:
            svc = await get_service_fn()
            await svc.dispatch_pending_tasks()
        except Exception as exc:
            logger.error("task_dispatcher.error", error=str(exc), exc_info=True)
        await asyncio.sleep(5)


def start_dispatcher(get_service_fn) -> None:
    """
    Запустить фоновый цикл диспетчеризации.
    Вызывать из register_startup в router.py.
    get_service_fn: async callable → TaskService
    """
    global _dispatcher_task
    _dispatcher_task = asyncio.create_task(
        _task_dispatcher_loop(get_service_fn),
        name="task_dispatcher",
    )
