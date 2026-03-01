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
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
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

        # Идемпотентность: защита от дублирующих вызовов.
        # Задача считается зависшей (stale) в двух случаях:
        #   1. Устройство ОФФЛАЙН — агент отключился, задача никогда не завершится
        #   2. Абсолютный предохранитель: задача висит >24 часов (баг на агенте)
        # Во всех остальных случаях — 409, задача реально работает.
        duplicate = await self.db.scalar(
            select(Task).where(
                Task.device_id == device_id,
                Task.org_id == org_id,
                Task.script_version_id == script.current_version_id,
                Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.ASSIGNED]),
            ).limit(1)
        )
        if duplicate:
            is_stale = False
            stale_reason = ""

            # Проверка 1: устройство оффлайн — задача точно зависла
            if self.status_cache:
                device_live = await self.status_cache.get_status(str(device_id))
                if not device_live or device_live.status not in ("online", "busy"):
                    is_stale = True
                    stale_reason = (
                        f"Устройство оффлайн (status="
                        f"{device_live.status if device_live else 'нет в кэше'}), "
                        f"задача не может завершиться"
                    )

            # Проверка 2: абсолютный таймаут 24 часа — защита от забытых задач
            if not is_stale:
                task_age = duplicate.updated_at or duplicate.created_at
                absolute_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                if task_age < absolute_cutoff:
                    is_stale = True
                    stale_reason = f"Задача висит >24ч (с {task_age.isoformat()})"

            if is_stale:
                logger.warning(
                    "task.stale_auto_timeout",
                    stale_task_id=str(duplicate.id),
                    device_id=str(device_id),
                    old_status=duplicate.status,
                    reason=stale_reason,
                )
                duplicate.status = TaskStatus.TIMEOUT
                duplicate.finished_at = datetime.now(timezone.utc)
                duplicate.error_message = f"Автоматический таймаут: {stale_reason}"
                await self.db.flush()
            else:
                raise HTTPException(
                    status_code=409,
                    detail=f"Task already queued/running for device (task_id={duplicate.id})",
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

        all_device_ids = await self.status_cache.get_all_tracked_device_ids()

        for device_id_str in all_device_ids:
            # Проверяем что устройство действительно ONLINE перед диспетчеризацией
            device_status = await self.status_cache.get_status(device_id_str)
            if not device_status or device_status.status != "online":
                continue

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
                    task.status = TaskStatus.FAILED
                    task.error_message = "Script version not found"
                    continue

                # Загрузить скрипт для имени (ScriptCacheManager на APK использует dag_name)
                script = await self.db.get(Script, task.script_id)
                dag_name = script.name if script else f"script_{task.script_id}"

                # Content-addressable hash для ScriptCacheManager на APK
                dag_json_str = json.dumps(version.dag, sort_keys=True, ensure_ascii=False)
                dag_hash = hashlib.sha256(dag_json_str.encode("utf-8")).hexdigest()

                delivered = False
                if self.publisher:
                    delivered = await self.publisher.send_command_live(
                        device_id_str,
                        {
                            "command_id": task_id_str,
                            "type": "EXECUTE_DAG",
                            "signed_at": int(datetime.now(timezone.utc).timestamp()),
                            "ttl_seconds": task.timeout_seconds,
                            "payload": {
                                "task_id": task_id_str,
                                "dag": version.dag,
                                "dag_name": dag_name,
                                "dag_hash": dag_hash,
                                "timeout_ms": task.timeout_seconds * 1000,
                            },
                        },
                    )

                if delivered:
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now(timezone.utc)
                    logger.info("task.dispatched", task_id=task_id_str, device_id=device_id_str)
                else:
                    # Агент оффлайн — освободить lock и вернуть задачу в очередь
                    await self.queue.mark_completed(task_id_str, device_id_str)
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

        # ── TaskBatch авто-агрегация: обновить счётчики succeeded/failed/status ──
        if task.batch_id:
            await self._aggregate_batch(task.batch_id, success)

    # ── TaskBatch авто-агрегация ────────────────────────────────────────────

    async def _aggregate_batch(self, batch_id: uuid.UUID, success: bool) -> None:
        """
        Инкрементально обновить счётчики батча.
        Когда все задачи завершены — вычислить финальный статус.
        """
        batch = await self.db.get(TaskBatch, batch_id)
        if not batch:
            return

        if success:
            batch.succeeded = (batch.succeeded or 0) + 1
        else:
            batch.failed = (batch.failed or 0) + 1

        completed_count = (batch.succeeded or 0) + (batch.failed or 0)

        if completed_count >= batch.total:
            # Все задачи завершены — вычисляем финальный статус
            if batch.failed == 0:
                batch.status = TaskBatchStatus.COMPLETED
            elif batch.succeeded == 0:
                batch.status = TaskBatchStatus.FAILED
            else:
                batch.status = TaskBatchStatus.PARTIAL
            logger.info(
                "batch.auto_aggregated",
                batch_id=str(batch_id),
                status=batch.status,
                succeeded=batch.succeeded,
                failed=batch.failed,
            )
        elif batch.status == TaskBatchStatus.PENDING:
            batch.status = TaskBatchStatus.RUNNING

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

    # ── Force Stop (running task) ─────────────────────────────────────────

    async def force_stop_task(
        self, task_id: uuid.UUID, org_id: uuid.UUID
    ) -> Task:
        """
        Принудительная остановка RUNNING задачи:
        1. Отправляет CANCEL_DAG через WebSocket агенту
        2. Освобождает Redis lock
        3. Обновляет статус в БД
        """
        task = await self._get_task(task_id, org_id)

        if task.status not in (TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot stop task in status '{task.status}'",
            )

        # Если задача QUEUED/ASSIGNED — просто отменяем через обычный путь
        if task.status in (TaskStatus.QUEUED, TaskStatus.ASSIGNED):
            await self.queue.cancel_task(str(task_id), str(org_id))
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.now(timezone.utc)
            logger.info("task.force_stopped.queued", task_id=str(task_id))
            return task

        # RUNNING — отправляем CANCEL_DAG агенту через WebSocket
        device_id_str = str(task.device_id)
        if self.publisher:
            await self.publisher.send_command_live(
                device_id_str,
                {
                    "command_id": str(task_id),
                    "type": "CANCEL_DAG",
                    "signed_at": int(datetime.now(timezone.utc).timestamp()),
                    "payload": {"task_id": str(task_id)},
                },
            )

        # Освобождаем Redis lock
        await self.queue.mark_completed(str(task_id), device_id_str)

        task.status = TaskStatus.CANCELLED
        task.finished_at = datetime.now(timezone.utc)
        task.error_message = "Force stopped by user"

        logger.info(
            "task.force_stopped",
            task_id=str(task_id),
            device_id=device_id_str,
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


async def _task_dispatcher_loop(dispatch_fn) -> None:
    """Dispatcher loop. dispatch_fn() handles its own session lifecycle."""
    logger.info("task_dispatcher.started", interval_s=5)
    while True:
        try:
            await dispatch_fn()
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
