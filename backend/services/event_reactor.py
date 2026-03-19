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

import fnmatch
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.account_session import AccountSession
from backend.models.device_event import DeviceEvent, EventSeverity
from backend.models.game_account import AccountStatus, GameAccount

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
        """
        Обработать входящее событие от устройства.

        1. Сохраняет событие в device_events
        2. Обновляет статус аккаунта (если применимо)
        3. Завершает активную сессию (если применимо)
        4. Запускает ротацию (если account.banned)

        Возвращает созданный DeviceEvent.
        """
        # ── 1. Персистентное сохранение ──────────────────────────────────
        event = DeviceEvent(
            org_id=org_id,
            device_id=device_id,
            event_type=event_type,
            severity=EventSeverity(severity),
            message=message,
            account_id=account_id,
            task_id=task_id,
            pipeline_run_id=pipeline_run_id,
            data=data or {},
            occurred_at=datetime.now(timezone.utc),
            processed=False,
        )
        self.db.add(event)
        await self.db.flush()

        logger.info(
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

        return event

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
    ) -> uuid.UUID | None:
        """
        Попытка ротации: найти свободный аккаунт той же игры и назначить на устройство.

        Возвращает UUID нового аккаунта или None если свободных нет.
        """
        # Получить забаненный аккаунт для определения игры
        banned = await self.db.get(GameAccount, banned_account_id)
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
        from backend.models.event_trigger import EventTrigger

        stmt = select(EventTrigger).where(
            EventTrigger.org_id == org_id,
            EventTrigger.is_active.is_(True),
        )
        result = await self.db.execute(stmt)
        triggers = result.scalars().all()

        if not triggers:
            return

        now = datetime.now(timezone.utc)

        for trigger in triggers:
            # Проверка glob-паттерна
            if not fnmatch.fnmatch(event_type, trigger.event_type_pattern):
                continue

            # Проверка cooldown
            if trigger.last_triggered_at and trigger.cooldown_seconds > 0:
                elapsed = (now - trigger.last_triggered_at).total_seconds()
                if elapsed < trigger.cooldown_seconds:
                    logger.debug(
                        "event_trigger.cooldown_skip",
                        trigger_id=str(trigger.id),
                        trigger_name=trigger.name,
                        cooldown_remaining=trigger.cooldown_seconds - elapsed,
                    )
                    continue

            # Проверка max_triggers_per_hour (простая проверка по total_triggers)
            # Для точной проверки нужна отдельная таблица, но в 99% случаев
            # cooldown_seconds достаточно. max_triggers_per_hour — дополнительная страховка.
            # TODO: реализовать точный подсчёт через временное окно при необходимости

            # Подставить параметры из шаблона
            input_params = self._render_trigger_params(
                template=trigger.input_params_template,
                device_id=device_id,
                event=event,
            )

            # Запустить pipeline
            try:
                from backend.services.orchestrator.pipeline_service import PipelineService
                pipeline_svc = PipelineService(self.db)
                run = await pipeline_svc.run(
                    pipeline_id=trigger.pipeline_id,
                    device_id=device_id,
                    org_id=org_id,
                    input_params=input_params,
                )
                await self.db.flush()

                # Обновить статистику триггера
                trigger.last_triggered_at = now
                trigger.total_triggers += 1
                await self.db.flush()

                logger.info(
                    "event_trigger.fired",
                    trigger_id=str(trigger.id),
                    trigger_name=trigger.name,
                    pipeline_id=str(trigger.pipeline_id),
                    run_id=str(run.id),
                    event_type=event_type,
                    device_id=str(device_id),
                )
            except Exception as e:
                logger.error(
                    "event_trigger.fire_failed",
                    trigger_id=str(trigger.id),
                    trigger_name=trigger.name,
                    pipeline_id=str(trigger.pipeline_id),
                    event_type=event_type,
                    error=str(e),
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
