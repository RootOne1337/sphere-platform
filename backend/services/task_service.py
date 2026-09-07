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
import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.device import Device
from backend.models.game_account import GameAccount
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.services.account_credentials import read_account_password
from backend.services.task_queue import TaskQueue

logger = structlog.get_logger()

# Глобальный set для фоновых webhook-задач — защита от GC (HIGH-5)
_pending_webhook_tasks: set[asyncio.Task] = set()


class TaskService:
    def __init__(
        self,
        db: AsyncSession,
        queue: TaskQueue | None = None,
        status_cache: Any | None = None,
        publisher: Any | None = None,
    ) -> None:
        self.db = db
        self.queue = queue if queue is not None else TaskQueue(None)
        self.status_cache = status_cache
        self.publisher = publisher

    # Регулярное выражение для плейсхолдеров {{account.xxx}} в DAG-нодах
    _PLACEHOLDER_RE = re.compile(r"\{\{account\.(\w+)\}\}")

    # ── Вспомогательные ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_dag_placeholders(dag: dict, variables: dict[str, str]) -> dict:
        """
        Рекурсивно обходит DAG JSON и заменяет плейсхолдеры {{account.xxx}}
        на реальные значения из словаря variables.
        Возвращает глубокую копию DAG — оригинал не мутируется.
        """
        dag_copy = copy.deepcopy(dag)

        def _walk(obj: Any) -> Any:
            if isinstance(obj, str):
                return TaskService._PLACEHOLDER_RE.sub(
                    lambda m: variables.get(m.group(1), m.group(0)),
                    obj,
                )
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_walk(item) for item in obj]
            return obj

        return _walk(dag_copy)

    @staticmethod
    def _build_account_variables(account: GameAccount) -> dict[str, str]:
        """
        Строит словарь переменных для подстановки в DAG из модели GameAccount.
        Ключи соответствуют суффиксам плейсхолдеров: {{account.<key>}}.
        """
        nickname = account.nickname or account.login or ""
        parts = nickname.split("_", 1)
        nick_part1 = parts[0] if parts else nickname
        nick_part2 = parts[1] if len(parts) > 1 else ""

        return {
            "login": account.login or "",
            "password": read_account_password(account),
            "nickname": nickname,
            "nick_part1": nick_part1,
            "nick_part2": nick_part2,
            "server_name": account.server_name or "",
            "game": account.game or "",
            "gender": account.gender.value if account.gender else "male",
        }

    async def _load_account_for_task(self, task: Task) -> GameAccount | None:
        """
        Загружает GameAccount, связанный с задачей.
        Ищет по account_id из input_params, или по device_id задачи.
        """
        # Приоритет 1: явный account_id в input_params
        account_id_raw = (task.input_params or {}).get("account_id")
        if account_id_raw:
            try:
                return await self.db.scalar(select(GameAccount).where(
                    GameAccount.id == uuid.UUID(str(account_id_raw)),
                    GameAccount.org_id == task.org_id,
                ))
            except (ValueError, TypeError):
                pass

        # Приоритет 2: аккаунт, назначенный на устройство задачи
        return await self.db.scalar(
            select(GameAccount).where(
                GameAccount.device_id == task.device_id,
                GameAccount.org_id == task.org_id,
                GameAccount.status.in_(["in_use", "free"]),
            ).order_by(GameAccount.assigned_at.desc().nulls_last()).limit(1)
        )

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
            ).with_for_update()
        )
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return device

    async def _get_task(
        self, task_id: uuid.UUID, org_id: uuid.UUID, *, for_update: bool = False
    ) -> Task:
        statement = (
            select(Task)
            .options(selectinload(Task.device), selectinload(Task.script))
            .where(Task.id == task_id, Task.org_id == org_id)
        )
        if for_update:
            # Serialize mutations with result handlers and watchdogs, refreshing
            # any earlier identity-map snapshot after the row lock is acquired.
            statement = statement.with_for_update().execution_options(populate_existing=True)
        task = await self.db.scalar(statement)
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
        account_id: uuid.UUID | None = None,
        batch_id: uuid.UUID | None = None,
        wave_index: int | None = None,
    ) -> Task:
        script = await self._get_script(script_id, org_id)
        if not script.current_version_id:
            raise HTTPException(status_code=400, detail="Script has no versions")

        await self._get_device(device_id, org_id)
        if account_id and not await self.db.scalar(select(GameAccount.id).where(
            GameAccount.id == account_id, GameAccount.org_id == org_id,
        )):
            raise HTTPException(status_code=404, detail="Account not found")

        # The device lock serializes competing creators through commit/rollback.
        # Missing presence or an old heartbeat cannot prove an APK stopped work.
        # Leave recovery/cancellation to the explicit task lifecycle, never a retry.
        duplicate = await self.db.scalar(
            select(Task).where(
                Task.device_id == device_id,
                Task.org_id == org_id,
                Task.script_version_id == script.current_version_id,
                Task.status.in_([TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.ASSIGNED]),
            ).limit(1)
        )
        if duplicate:
            raise HTTPException(
                status_code=409,
                detail=f"Task already queued/running for device (task_id={duplicate.id})",
            )

        input_params: dict = {"priority": priority}
        if webhook_url:
            input_params["webhook_url"] = webhook_url
        if account_id:
            input_params["account_id"] = str(account_id)

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
        # The committed QUEUED row is the durable dispatch intent.
        # Publishing to Redis here would escape a caller's transaction rollback.
        logger.info(
            "task.created",
            task_id=str(task.id),
            device_id=str(device_id),
            priority=priority,
        )
        return task

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def dispatch_pending_tasks(self) -> None:
        """Dispatch committed intent using this dispatcher's dedicated DB session.

        A device row serializes competing dispatchers. ASSIGNED is committed
        before sending; until the agent acknowledges receipt, the same task ID
        is retried. Redis is transport/presence, never the source of task intent.
        """
        if not self.status_cache:
            return

        candidates = list(await self.db.scalars(
            select(Task.device_id).where(
                Task.status.in_([TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            ).distinct()
        ))
        await self.db.rollback()
        presence_by_id = {}
        # Batched MGET avoids one Redis round trip per pending device. Do not
        # truncate candidates before filtering offline/busy devices: that can
        # permanently starve later devices in a large fleet.
        for offset in range(0, len(candidates), 512):
            async with asyncio.timeout(2):
                presence_by_id.update(await self.status_cache.bulk_get_status(
                    [str(value) for value in candidates[offset:offset + 512]],
                ))
        for device_id in candidates:
            task_id_str = None
            try:
                presence = presence_by_id.get(str(device_id))
                if not presence or presence.status not in ("online", "busy"):
                    await self.db.rollback()
                    continue
                device = await self.db.scalar(select(Device).where(
                    Device.id == device_id, Device.is_active.is_(True),
                ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
                if device is None:
                    await self.db.rollback()
                    continue

                task = await self.db.scalar(select(Task).where(
                    Task.device_id == device_id, Task.org_id == device.org_id,
                    Task.status.in_([TaskStatus.ASSIGNED, TaskStatus.RUNNING]),
                ).order_by(Task.created_at).limit(1).with_for_update()
                    .execution_options(populate_existing=True))
                now = datetime.now(timezone.utc)
                if task is not None and (
                    task.status == TaskStatus.RUNNING or
                    task.updated_at > now - timedelta(seconds=30)
                ):
                    await self.db.rollback()
                    continue
                if task is None:
                    task = await self.db.scalar(select(Task).where(
                        Task.device_id == device_id, Task.org_id == device.org_id,
                        Task.status == TaskStatus.QUEUED,
                    ).order_by(Task.priority, Task.created_at, Task.id).limit(1)
                        .with_for_update().execution_options(populate_existing=True))
                if task is None:
                    await self.db.rollback()
                    continue

                task_id_str = str(task.id)
                version = await self.db.scalar(select(ScriptVersion).where(
                    ScriptVersion.id == task.script_version_id,
                    ScriptVersion.script_id == task.script_id,
                    ScriptVersion.org_id == task.org_id,
                ))
                if version is None:
                    task.status = TaskStatus.FAILED
                    task.error_message = "Script version not found"
                    task.finished_at = now
                    await self.db.commit()
                    continue
                script = await self.db.get(Script, task.script_id)
                resolved_dag = version.dag
                account = await self._load_account_for_task(task)
                if account is not None:
                    resolved_dag = self._resolve_dag_placeholders(
                        version.dag, self._build_account_variables(account),
                    )
                dag_json = json.dumps(resolved_dag, sort_keys=True, ensure_ascii=False)
                command = {
                    "command_id": task_id_str,
                    "type": "EXECUTE_DAG",
                    "signed_at": int(now.timestamp()),
                    "ttl_seconds": task.timeout_seconds,
                    "payload": {
                        "task_id": task_id_str,
                        "dag": resolved_dag,
                        "dag_name": script.name if script else f"script_{task.script_id}",
                        "dag_hash": hashlib.sha256(dag_json.encode("utf-8")).hexdigest(),
                        "timeout_ms": task.timeout_seconds * 1000,
                    },
                }
                task.status = TaskStatus.ASSIGNED
                task.updated_at = now
                await self.db.commit()

                delivered = bool(self.publisher and await self.publisher.send_command_live(
                    str(device_id), command,
                ))
                logger.info("task.assignment_sent", task_id=task_id_str,
                            device_id=str(device_id), transport_accepted=delivered)
                # Only the device's received/running acknowledgement advances
                # ASSIGNED. A send return value cannot prove remote receipt.
            except asyncio.CancelledError:
                await self.db.rollback()
                raise
            except Exception as exc:
                await self.db.rollback()
                logger.warning("task.dispatch_retry_pending", task_id=task_id_str,
                               device_id=str(device_id), error=str(exc))

    # ── Безопасное освобождение running lock ─────────────────────────────────

    async def _safe_mark_completed(self, task_id: str, device_id: str) -> None:
        """
        Освобождает running lock устройства, только если он принадлежит данной задаче.
        Предотвращает случайное освобождение lock-а, который уже занят следующей задачей.
        """
        try:
            await self.queue.mark_completed(task_id, device_id)
        except Exception as exc:
            # A Redis outage must not roll back a durable task result. A retry
            # of the terminal result will attempt the conditional release again.
            logger.warning("task.result.queue_release_failed", task_id=task_id, error=str(exc))

    # ── Result handling ──────────────────────────────────────────────────────

    async def handle_task_result(
        self,
        task_id: str,
        device_id: str,
        result: dict,
        org_id: str | None = None,
    ) -> bool:
        """Вызывается при получении command_result от агента (TZ-03 WebSocket)."""
        task = await self.db.scalar(select(Task).where(
            Task.id == uuid.UUID(task_id), Task.device_id == uuid.UUID(device_id),
            *([Task.org_id == uuid.UUID(org_id)] if org_id is not None else []),
        ).with_for_update())
        if not task:
            logger.warning("task.result.not_found", task_id=task_id)
            return False

        # FIX BUG-2: Не перезаписываем финальные статусы.
        # Если планировщик уже поставил CANCELLED (conflict_policy=cancel),
        # result от агента не должен перезаписывать его на COMPLETED/FAILED.
        if task.status in (TaskStatus.CANCELLED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT):
            logger.info(
                "task.result.ignored_final_status",
                task_id=task_id,
                current_status=task.status,
            )
            # Результат сохраняем для диагностики, но статус не меняем
            # Освобождаем running lock только если он принадлежит ЭТОЙ задаче
            await self._safe_mark_completed(task_id, device_id)
            return True

        success = result.get("success", False)
        task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
        task.finished_at = datetime.now(timezone.utc)
        task.result = result
        task.error_message = result.get("error")

        # FIX BUG-2: Безопасное освобождение — только если lock принадлежит этой задаче
        await self._safe_mark_completed(task_id, device_id)
        logger.info(
            "task.completed",
            task_id=task_id,
            success=success,
            device_id=device_id,
        )

        # ── EventReactor: эмиссия task.completed / task.failed ──────────────
        # Позволяет EventTrigger'ам автоматически запускать pipeline
        # при успехе/неуспехе задачи (GENERIC — любые сценарии).
        try:
            from backend.services.event_reactor import EventReactor
            event_type = "task.completed" if success else "task.failed"
            reactor = EventReactor(self.db)
            await reactor.process_event(
                org_id=task.org_id,
                device_id=uuid.UUID(device_id),
                event_type=event_type,
                severity="info" if success else "warning",
                message=result.get("error") if not success else None,
                task_id=task.id,
                pipeline_run_id=None,
                data={
                    "task_id": str(task.id),
                    "script_id": str(task.script_id) if task.script_id else None,
                    "success": success,
                },
            )
        except Exception as e:
            logger.warning(
                "task_result.event_emission_failed",
                task_id=task_id,
                error=str(e),
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
        return True

    # ── TaskBatch авто-агрегация ────────────────────────────────────────────

    async def _aggregate_batch(self, batch_id: uuid.UUID, success: bool, *, count: int = 1) -> None:
        """
        Инкрементально обновить счётчики батча.
        Когда все задачи завершены — вычислить финальный статус.
        """
        # Result handlers and watchdogs share this lock. Refresh preloaded ORM
        # values after waiting so no worker overwrites a committed increment.
        batch = await self.db.scalar(select(TaskBatch).where(
            TaskBatch.id == batch_id,
        ).with_for_update().execution_options(populate_existing=True))
        if not batch:
            return

        if success:
            batch.succeeded = (batch.succeeded or 0) + count
        else:
            batch.failed = (batch.failed or 0) + count

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
        task = await self._get_task(task_id, org_id, for_update=True)

        if task.status not in (TaskStatus.QUEUED, TaskStatus.ASSIGNED):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel task in status '{task.status}'",
            )

        removed = await self.queue.cancel_task(str(task_id), str(org_id), str(task.device_id))
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
        task = await self._get_task(task_id, org_id, for_update=True)

        if task.status not in (TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot stop task in status '{task.status}'",
            )

        # Если задача QUEUED/ASSIGNED — просто отменяем через обычный путь
        if task.status in (TaskStatus.QUEUED, TaskStatus.ASSIGNED):
            await self.queue.cancel_task(str(task_id), str(org_id), str(task.device_id))
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
                    # A control receipt must not enter the DAG result handler,
                    # including when cancellation's SQL transaction rolls back.
                    "command_id": f"user_cancel_{task_id}",
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
                    stmt.options(
                        selectinload(Task.device),
                        selectinload(Task.script),
                    )
                    .order_by(Task.created_at.desc())
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
