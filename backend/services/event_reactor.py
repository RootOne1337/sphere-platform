# backend/services/event_reactor.py
# ВЛАДЕЛЕЦ: TZ-11 Event Reactor — автоматическая реакция на события устройств.
#
# EventReactor подписывается на Redis PubSub-канал событий и выполняет:
# 1. Персистентное сохранение в device_events (через DeviceEventService)
# 2. Автоматические реакции:
#    - account.banned → перевод аккаунта в BANNED, ротация на свободный
#    - account.captcha → перевод аккаунта в CAPTCHA, уведомление
#    - game.crashed → логирование, инкремент ошибок
#    - device.error → логирование, уведомление
# 3. Завершение активной сессии аккаунта при бане/капче/ошибке
# 4. Проверка EventTrigger'ов — автоматический запуск pipeline по событиям (GENERIC)
#
# Запускается как фоновая задача при старте бэкенда.
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Insert

from backend.models.account_session import AccountSession
from backend.models.device import Device
from backend.models.device_event import DeviceEvent, EventSeverity
from backend.models.event_trigger import EventTrigger
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.pipeline import Pipeline, PipelineRun
from backend.models.task import Task
from backend.services.application_account_scope import resolve_application_account_scope
from backend.services.event_trigger_admission import (
    inspect_trigger,
    trigger_clock,
    trigger_pattern_matches,
    trigger_root_available,
)

logger = structlog.get_logger()


# ══════════════════════════════════════════════════════════════════════════
# Определение правил реакции
# ══════════════════════════════════════════════════════════════════════════

# Маппинг event_type → новый статус аккаунта (если событие связано с аккаунтом)
ACCOUNT_STATUS_REACTIONS: dict[str, AccountStatus] = {
    "account.banned": AccountStatus.banned,
    "account.captcha": AccountStatus.captcha,
    "account.phone_verify": AccountStatus.phone_verify,
    "account.error": AccountStatus.disabled,
}

# Причины завершения сессии по event_type
SESSION_END_REASONS: dict[str, str] = {
    "account.banned": "banned",
    "account.captcha": "captcha",
    "account.phone_verify": "error",
    "account.error": "error",
    "game.crashed": "error",
    "device.error": "device_offline",
    "device.offline": "device_offline",
}


class EventReactor:
    """
    Обработчик событий — реактивная бизнес-логика.

    Вызывается при получении события от агента (через WebSocket/Redis PubSub).
    Модифицирует состояние аккаунтов, завершает сессии, эмитирует уведомления.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def process_event(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID,
        event_type: str,
        severity: str = "info",
        message: str | None = None,
        account_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
        data: dict | None = None,
    ) -> DeviceEvent:
        event, _ = await self._process_event(
            org_id, device_id, event_type, severity, message, account_id, task_id, pipeline_run_id, data,
        )
        return event

    async def process_transport_event(
        self, org_id: uuid.UUID, device_id: uuid.UUID, event_type: str, severity: str,
        message: str | None, account_id: uuid.UUID | None, task_id: uuid.UUID | None,
        data: dict, source_event_id: uuid.UUID | None,
    ) -> tuple[DeviceEvent, bool]:
        """Persist one device event and report whether its transport key was replayed."""
        return await self._process_event(
            org_id, device_id, event_type, severity, message, account_id, task_id, data=data,
            source_event_id=source_event_id,
        )

    async def _process_event(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID,
        event_type: str,
        severity: str = "info",
        message: str | None = None,
        account_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        pipeline_run_id: uuid.UUID | None = None,
        data: dict | None = None,
        *,
        source_event_id: uuid.UUID | None = None,
    ) -> tuple[DeviceEvent, bool]:
        """
        Обработать входящее событие от устройства.

        1. Сохраняет событие в device_events
        2. Обновляет статус аккаунта (если применимо)
        3. Завершает активную сессию (если применимо)
        4. Запускает ротацию (если account.banned)

        Возвращает событие и признак повтора доставки.
        """
        # Resolve ancestry from the task row and its pipeline link. Agent-supplied
        # pipeline IDs or arbitrary payload fields never become causal metadata.
        task_id, origin = await self._find_task_origin(org_id, device_id, task_id)
        if origin is not None:
            pipeline_run_id = origin.id
        path = None
        if origin is not None:
            path = origin.trigger_path or ([str(origin.event_trigger_id)] if origin.event_trigger_id else [])
        root_id = (origin.trigger_root_event_id or origin.trigger_event_id) if origin is not None else None

        # The transport event key is scoped to the authenticated device. Reserve
        # it before account/device locks or mutations, and let the unique index
        # arbitrate concurrent deliveries. A rollback releases the reservation.
        event: DeviceEvent | None = None
        if source_event_id is not None:
            event, replayed = await self._persist_transport_event(
                org_id, device_id, event_type, severity, message, task_id, pipeline_run_id,
                data or {}, source_event_id, root_id, path,
            )
            if replayed:
                return event, True
        scope = None
        if account_id and (event_type in ACCOUNT_STATUS_REACTIONS or event_type in SESSION_END_REASONS):
            device = await self.db.scalar(select(Device).where(
                Device.id == device_id, Device.org_id == org_id,
            ).with_for_update(key_share=True).execution_options(populate_existing=True))
            if device is not None:
                try:
                    scope = await resolve_application_account_scope(self.db, device)
                except HTTPException:
                    account_id = None
                if scope is not None:
                    account = await self.db.scalar(select(GameAccount).where(
                        GameAccount.id == account_id, GameAccount.org_id == org_id,
                        GameAccount.device_id == device_id, GameAccount.game == scope[0],
                        GameAccount.server_name == scope[1],
                    ).with_for_update().execution_options(populate_existing=True))
                    if account is None:
                        account_id = None

        # ── 1. Персистентное сохранение ──────────────────────────────────
        if event is None:
            event = DeviceEvent(
                org_id=org_id, device_id=device_id, event_type=event_type,
                severity=EventSeverity(severity), message=message, task_id=task_id,
                pipeline_run_id=pipeline_run_id, data=data or {}, occurred_at=datetime.now(timezone.utc),
                trigger_root_event_id=root_id, trigger_path=path, processed=False,
            )
            self.db.add(event)
        event.account_id = account_id
        await self.db.flush()

        logger.debug(
            "event_reactor.event_saved",
            event_id=str(event.id),
            event_type=event_type,
            device_id=str(device_id),
            account_id=str(account_id) if account_id else None,
        )

        # ── 2. Реакция на статус аккаунта ────────────────────────────────
        new_status = ACCOUNT_STATUS_REACTIONS.get(event_type)
        if new_status and account_id:
            await self._update_account_status(
                account_id=account_id,
                org_id=org_id,
                new_status=new_status,
                reason=message or event_type,
                event_type=event_type,
            )

        # ── 3. Завершение активной сессии ────────────────────────────────
        end_reason = SESSION_END_REASONS.get(event_type)
        if end_reason and account_id:
            await self._end_active_session(
                account_id=account_id,
                org_id=org_id,
                end_reason=end_reason,
                error_message=message,
            )

        # ── 4. Ротация при бане ──────────────────────────────────────────
        if event_type == "account.banned" and account_id:
            rotated = await self._try_rotate_account(
                device_id=device_id,
                org_id=org_id,
                banned_account_id=account_id,
                scope=scope,
            )
            if rotated:
                event.data = {**event.data, "rotation": "success", "new_account_id": str(rotated)}
            else:
                event.data = {**event.data, "rotation": "no_free_accounts"}

        # ── 5. Проверка EventTrigger'ов — GENERIC запуск pipeline ────────
        await self._check_event_triggers(
            org_id=org_id,
            device_id=device_id,
            event_type=event_type,
            event=event,
        )

        # Пометить как обработанное
        event.processed = True
        await self.db.flush()

        return event, False

    async def _find_task_origin(
        self, org_id: uuid.UUID, device_id: uuid.UUID, task_id: uuid.UUID | None,
    ) -> tuple[uuid.UUID | None, PipelineRun | None]:
        if task_id is None:
            return None, None
        task = await self.db.scalar(select(Task).where(
            Task.id == task_id, Task.org_id == org_id, Task.device_id == device_id,
        ))
        if task is None:
            return None, None
        # In-flight children created before the migration only have the inverse
        # current_task_id link. New children retain provenance after step advance.
        owner = PipelineRun.id == task.pipeline_run_id if task.pipeline_run_id is not None else (
            and_(PipelineRun.current_task_id.is_not(None), PipelineRun.current_task_id == task.id)
        )
        origin = await self.db.scalar(select(PipelineRun).where(
            owner, PipelineRun.org_id == org_id, PipelineRun.device_id == device_id,
        ).limit(1))
        return task_id, origin

    async def _persist_transport_event(
        self, org_id: uuid.UUID, device_id: uuid.UUID, event_type: str, severity: str, message: str | None,
        task_id: uuid.UUID | None, pipeline_run_id: uuid.UUID | None, data: dict, source_event_id: uuid.UUID,
        root_id: uuid.UUID | None, path: list[str] | None,
    ) -> tuple[DeviceEvent, bool]:
        values = dict(
            org_id=org_id, device_id=device_id, event_type=event_type, severity=EventSeverity(severity),
            message=message, task_id=task_id, pipeline_run_id=pipeline_run_id, data=data,
            source_event_id=source_event_id, trigger_root_event_id=root_id, trigger_path=path,
            occurred_at=datetime.now(timezone.utc), processed=False,
        )
        identity = ["org_id", "device_id", "source_event_id"]
        statement: Insert
        if self.db.get_bind().dialect.name == "sqlite":
            statement = sqlite_insert(DeviceEvent).values(**values).on_conflict_do_nothing(index_elements=identity)
        else:
            statement = pg_insert(DeviceEvent).values(**values).on_conflict_do_nothing(
                index_elements=identity, index_where=DeviceEvent.source_event_id.is_not(None),
            )
        event_id = await self.db.scalar(statement.returning(DeviceEvent.id))
        event = await self.db.scalar(select(DeviceEvent).where(
            DeviceEvent.org_id == org_id, DeviceEvent.device_id == device_id, DeviceEvent.source_event_id == source_event_id,
        ))
        if event is None:
            raise RuntimeError("Device event reservation is unavailable")
        return event, event_id is None

    # ── Внутренние методы ────────────────────────────────────────────────

    async def _update_account_status(
        self,
        account_id: uuid.UUID,
        org_id: uuid.UUID,
        new_status: AccountStatus,
        reason: str,
        event_type: str,
    ) -> None:
        """Обновить статус аккаунта по результатам события."""
        stmt = select(GameAccount).where(
            GameAccount.id == account_id,
            GameAccount.org_id == org_id,
        )
        account = (await self.db.execute(stmt)).scalar_one_or_none()
        if not account:
            logger.warning("event_reactor.account_not_found", account_id=str(account_id))
            return

        old_status = account.status
        account.status = new_status
        account.status_reason = reason
        account.status_changed_at = datetime.now(timezone.utc)

        # Отвязать от устройства при бане/ошибке
        if new_status in (AccountStatus.banned, AccountStatus.disabled):
            account.device_id = None
            account.assigned_at = None

        # Инкрементировать счётчик банов
        if event_type == "account.banned":
            account.total_bans += 1
            account.last_ban_at = datetime.now(timezone.utc)
            account.ban_reason = reason

        await self.db.flush()

        logger.info(
            "event_reactor.account_status_changed",
            account_id=str(account_id),
            old_status=old_status.value if isinstance(old_status, AccountStatus) else str(old_status),
            new_status=new_status.value,
            reason=reason,
        )

    async def _end_active_session(
        self,
        account_id: uuid.UUID,
        org_id: uuid.UUID,
        end_reason: str,
        error_message: str | None = None,
    ) -> None:
        """Завершить активную сессию аккаунта."""
        from backend.models.account_session import SessionEndReason

        stmt = select(AccountSession).where(
            AccountSession.account_id == account_id,
            AccountSession.org_id == org_id,
            AccountSession.ended_at.is_(None),
        )
        session = (await self.db.execute(stmt)).scalar_one_or_none()
        if not session:
            return

        session.ended_at = datetime.now(timezone.utc)
        session.end_reason = SessionEndReason(end_reason)
        session.error_message = error_message

        # Обновить level_after / balance_after из текущего состояния аккаунта
        account = await self.db.get(GameAccount, account_id)
        if account:
            session.level_after = account.level
            session.balance_after = account.balance_rub
            # Инкрементировать total_sessions у аккаунта
            account.total_sessions += 1
            account.last_session_end = session.ended_at

        await self.db.flush()

        duration = 0
        _ended = session.ended_at
        _started = session.started_at
        if _ended is not None and _started is not None:
            duration = int((_ended - _started).total_seconds())
        logger.info(
            "event_reactor.session_ended",
            session_id=str(session.id),
            account_id=str(account_id),
            end_reason=end_reason,
            duration_seconds=duration,
        )

    async def _try_rotate_account(
        self,
        device_id: uuid.UUID,
        org_id: uuid.UUID,
        banned_account_id: uuid.UUID,
        scope: tuple[str, str] | None = None,
    ) -> uuid.UUID | None:
        """
        Попытка ротации: найти свободный аккаунт той же игры и назначить на устройство.

        Возвращает UUID нового аккаунта или None если свободных нет.
        """
        # Получить забаненный аккаунт для определения игры
        banned = await self.db.scalar(select(GameAccount).where(
            GameAccount.id == banned_account_id, GameAccount.org_id == org_id,
        ))
        if not banned:
            return None

        game = banned.game

        # Найти свободный аккаунт той же игры в той же организации
        stmt = (
            select(GameAccount)
            .where(
                GameAccount.org_id == org_id,
                GameAccount.game == game,
                GameAccount.status == AccountStatus.free,
                GameAccount.id != banned_account_id,
            )
            .order_by(GameAccount.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if scope is not None:
            stmt = stmt.where(GameAccount.server_name == scope[1], GameAccount.device_id.is_(None))
        free_account = (await self.db.execute(stmt)).scalar_one_or_none()
        if not free_account:
            logger.warning(
                "event_reactor.no_free_accounts",
                org_id=str(org_id),
                game=game,
                device_id=str(device_id),
            )
            return None

        # Назначить на устройство
        now = datetime.now(timezone.utc)
        free_account.status = AccountStatus.in_use
        free_account.device_id = device_id
        free_account.assigned_at = now
        free_account.status_changed_at = now
        free_account.status_reason = f"Автоматическая ротация (бан аккаунта {banned.login})"

        # Создать новую сессию
        new_session = AccountSession(
            org_id=org_id,
            account_id=free_account.id,
            device_id=device_id,
            started_at=now,
            level_before=free_account.level,
            balance_before=free_account.balance_rub,
            meta={"rotation_from": str(banned_account_id)},
        )
        self.db.add(new_session)
        await self.db.flush()

        logger.info(
            "event_reactor.account_rotated",
            old_account_id=str(banned_account_id),
            new_account_id=str(free_account.id),
            device_id=str(device_id),
            game=game,
        )
        return free_account.id

    async def _check_event_triggers(
        self,
        org_id: uuid.UUID,
        device_id: uuid.UUID,
        event_type: str,
        event: DeviceEvent,
    ) -> None:
        """
        Проверить все активные EventTrigger'ы для данного события.

        При совпадении event_type_pattern — запустить соответствующий pipeline.
        Учитывает cooldown_seconds и max_triggers_per_hour для анти-спама.
        Паттерн поддерживает glob (fnmatch): account.banned, account.*, task.* итд.
        """
        candidates = (await self.db.execute(select(EventTrigger.id, EventTrigger.event_type_pattern).where(
            EventTrigger.org_id == org_id,
            EventTrigger.is_active.is_(True),
        ).order_by(EventTrigger.id))).all()
        matching = [trigger_id for trigger_id, pattern in candidates if trigger_pattern_matches(event_type, pattern)]
        if not matching or not await trigger_root_available(self.db, event, lock=True):
            return
        # All admissions for a root lock the same persisted event before any
        # trigger rows. This serializes the shared budget across different rules.
        for trigger_id in matching:
            try:
                # A failed run admission must not roll back the event, its other
                # triggers, or any mutations done by the event's caller.
                async with self.db.begin_nested():
                    await self._admit_event_trigger(trigger_id, org_id, device_id, event)
            except Exception as exc:
                logger.error(
                    "event_trigger.fire_failed",
                    trigger_id=str(trigger_id), event_id=str(event.id), error_type=type(exc).__name__,
                )

    async def _admit_event_trigger(
        self, trigger_id: uuid.UUID, org_id: uuid.UUID, device_id: uuid.UUID, event: DeviceEvent,
    ) -> None:
        from backend.services.orchestrator.pipeline_service import PipelineService

        trigger = await self.db.scalar(select(EventTrigger).where(
            EventTrigger.id == trigger_id, EventTrigger.org_id == org_id,
        ).with_for_update().execution_options(populate_existing=True))
        if trigger is None or not trigger.is_active or not trigger_pattern_matches(
            event.event_type, trigger.event_type_pattern,
        ):
            return

        # Hold the definition lock before PipelineService.run, whose public
        # lock-conflict handler rolls back its whole session.
        active = await self.db.scalar(select(Pipeline.is_active).where(
            Pipeline.org_id == org_id, Pipeline.id == trigger.pipeline_id,
        ).with_for_update(read=True, nowait=True))
        now = await trigger_clock(self.db)
        decision = await inspect_trigger(self.db, trigger, event.event_type, now, pipeline_active=bool(active), event=event)
        if not decision.would_admit:
            logger.debug(
                "event_trigger.not_admitted", trigger_id=str(trigger.id), event_id=str(event.id),
                reason=decision.reason,
            )
            return

        run = await PipelineService(self.db).run(
            pipeline_id=trigger.pipeline_id, device_id=device_id, org_id=org_id,
            input_params=self._render_trigger_params(trigger.input_params_template, device_id, event),
        )
        run.event_trigger_id = trigger.id
        run.trigger_event_id = event.id
        run.trigger_accepted_at = now
        run.trigger_root_event_id = event.trigger_root_event_id or event.id
        run.trigger_path = [*(event.trigger_path or []), str(trigger.id)]
        trigger.last_triggered_at = now
        trigger.total_triggers += 1
        await self.db.flush()
        logger.debug(
            "event_trigger.admitted", trigger_id=str(trigger.id), event_id=str(event.id), run_id=str(run.id),
        )

    @staticmethod
    def _render_trigger_params(
        template: dict,
        device_id: uuid.UUID,
        event: DeviceEvent,
    ) -> dict:
        """
        Подставить плейсхолдеры в шаблон input_params_template.

        Поддерживаемые плейсхолдеры (в строковых значениях):
        - {device_id}       → UUID устройства
        - {account_id}      → UUID аккаунта (или пустая строка)
        - {event_type}      → тип события
        - {event_id}        → UUID event'а
        """
        replacements = {
            "{device_id}": str(device_id),
            "{account_id}": str(event.account_id) if event.account_id else "",
            "{event_type}": event.event_type,
            "{event_id}": str(event.id),
        }

        def _replace_value(value: object) -> object:
            if isinstance(value, str):
                for placeholder, replacement in replacements.items():
                    value = value.replace(placeholder, replacement)
                return value
            if isinstance(value, dict):
                return {k: _replace_value(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_replace_value(item) for item in value]
            return value

        return _replace_value(template)  # type: ignore[return-value]
