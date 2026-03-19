# backend/services/orchestrator/orchestration_engine.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# Фоновый движок оркестрации — полный контур автоматизации прокачки аккаунтов:
#
#   генерация ника → регистрация → фарм (циклический) → бан/готов → по кругу
#
# Цикл работы (каждые 10с):
#   1. Загружает PipelineSettings из БД (все орги)
#   2. Если orchestration_enabled=false → пропуск
#   3. Обработка завершённых задач → обновление статусов аккаунтов
#   4. Если registration_enabled → авто-создание аккаунтов + задач регистрации
#   5. Если farming_enabled → авто-запуск фарм-сессий для свободных аккаунтов
#   6. Мониторинг банов → авто-замена (если включено)
#
# Все данные берутся из БД → переживают перезагрузку сервера.
# Задачи помечаются CANCELLED после обработки, чтобы избежать повторной обработки.
from __future__ import annotations

import asyncio
import secrets
import string
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.database.engine import AsyncSessionLocal
from backend.models.device import Device
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.pipeline_settings import PipelineSettings
from backend.models.task import Task, TaskStatus

logger = structlog.get_logger()

# Интервал основного цикла (секунды)
_POLL_INTERVAL = 10.0

# Алфавит для генерации паролей (буквы + цифры)
_PASSWORD_ALPHABET = string.ascii_letters + string.digits
_PASSWORD_LENGTH = 12


class OrchestrationEngine:
    """
    Фоновый движок оркестрации — полный контур автоматизации.

    Полный жизненный цикл аккаунта:
      pending_registration → (задача регистрации) → free
        → (задача фарма) → in_use → (результат) →
           - level достигнут → free (готов, device_id/server_name сохраняются)
           - level НЕ достигнут → cooldown → (ждём) → free → снова фарм
           - бан → banned (device_id/server_name сохраняются в строке)
           - ошибка → free (повторная попытка)

    Один сервер может быть привязан к МНОГИМ устройствам.
    Аккаунт ВСЕГДА хранит server_name и device_id для истории.
    """

    def __init__(self) -> None:
        self._running = False

        # Статистика за текущую сессию (с рестарта сервера)
        self.stats_registrations_completed = 0
        self.stats_registrations_failed = 0
        self.stats_bans_detected = 0

    async def start(self) -> None:
        """Запуск фонового loop."""
        self._running = True
        logger.info("orchestration_engine.started")
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                logger.error("orchestration_engine.tick_error", error=str(exc), exc_info=True)
            await asyncio.sleep(_POLL_INTERVAL)

    async def stop(self) -> None:
        """Остановка движка."""
        self._running = False
        logger.info("orchestration_engine.stopped")

    # ── Основной цикл ────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        """Один цикл оркестрации — проверка всех организаций."""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(PipelineSettings))
            all_settings = result.scalars().all()

            for settings in all_settings:
                if not settings.orchestration_enabled:
                    continue
                try:
                    await self._process_org(db, settings)
                except Exception as exc:
                    logger.error(
                        "orchestration_engine.org_error",
                        org_id=str(settings.org_id),
                        error=str(exc),
                        exc_info=True,
                    )
            await db.commit()

    async def _process_org(self, db, settings: PipelineSettings) -> None:
        """Обработка одной организации — полный контур."""
        # 1. Сначала обработка результатов (чтобы освободить слоты)
        await self._process_completed_tasks(db, settings)

        # 2. Кулдаун → free (аккаунты с истёкшим кулдауном возвращаются в пул)
        await self._process_cooldowns(db, settings)

        # 3. Авто-регистрация новых аккаунтов
        if settings.registration_enabled and settings.registration_script_id:
            await self._process_registrations(db, settings)

        # 4. Авто-фарм свободных аккаунтов
        if settings.farming_enabled and settings.farming_script_id:
            await self._process_farming(db, settings)

        # 5. Авто-замена забаненных (если включено)
        if settings.ban_detection_enabled and settings.auto_replace_banned:
            await self._process_ban_replacement(db, settings)

    # ── Регистрация ──────────────────────────────────────────────────────────

    async def _process_registrations(self, db, settings: PipelineSettings) -> None:
        """
        Авто-регистрация:
        1. Считаем активные регистрации — проверяем лимит
        2. Находим устройства с server_name, online, без активных задач
        3. Для каждого свободного слота: генерируем ник → создаём аккаунт → задачу
        """
        org_id = settings.org_id

        # Подсчёт текущих регистраций
        result = await db.execute(
            select(func.count()).select_from(Task).where(
                Task.org_id == org_id,
                Task.script_id == settings.registration_script_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
        )
        active_count = result.scalar_one()
        if active_count >= settings.max_concurrent_registrations:
            return

        slots = settings.max_concurrent_registrations - active_count

        # Устройства с активными задачами (подзапрос)
        busy_devices_sq = (
            select(Task.device_id)
            .where(
                Task.org_id == org_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
            .scalar_subquery()
        )

        result = await db.execute(
            select(Device)
            .where(
                Device.org_id == org_id,
                Device.server_name.isnot(None),
                Device.is_active.is_(True),
                Device.id.notin_(busy_devices_sq),
            )
            .limit(slots)
        )
        devices = result.scalars().all()
        if not devices:
            return

        for device in devices:
            try:
                await self._create_registration_task(db, settings, device)
            except Exception as exc:
                logger.error(
                    "orchestration.reg_create_error",
                    device_id=str(device.id),
                    error=str(exc),
                )

    async def _create_registration_task(
        self, db, settings: PipelineSettings, device: Device
    ) -> None:
        """Генерация ника + создание аккаунта + задачи регистрации."""
        from backend.services.nick_generator import NickGenerator

        org_id = settings.org_id

        # Генерация уникального ника
        nick_gen = NickGenerator(db)
        pattern = settings.nick_pattern if settings.nick_generation_enabled else "{first_name}_{last_name}"
        nickname = await nick_gen.generate(org_id=str(org_id), pattern=pattern)

        # Безопасный пароль
        password = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH))

        # Аккаунт в pending_registration — привязан к device и server
        account = GameAccount(
            org_id=org_id,
            game="black_russia",
            login=nickname,
            password_encrypted=password,
            server_name=device.server_name,
            nickname=nickname,
            status=AccountStatus.pending_registration,
            status_reason="Авто-регистрация через оркестратор",
            status_changed_at=datetime.now(timezone.utc),
            device_id=device.id,
            assigned_at=datetime.now(timezone.utc),
            target_level=settings.default_target_level,
        )
        db.add(account)
        await db.flush()

        # Задача регистрации
        task = Task(
            org_id=org_id,
            device_id=device.id,
            script_id=settings.registration_script_id,
            status=TaskStatus.QUEUED,
            priority=10,
            timeout_seconds=settings.registration_timeout_seconds,
            input_params={
                "account_id": str(account.id),
                "nickname": nickname,
                "password": password,
                "server_name": device.server_name,
            },
        )
        db.add(task)
        await db.flush()

        # Enqueue в per-device Redis очередь
        await self._enqueue_task(org_id, device.id, task.id, task.priority)

        logger.info(
            "orchestration.reg_created",
            device=device.name,
            server=device.server_name,
            nick=nickname,
            task_id=str(task.id),
            account_id=str(account.id),
        )

    # ── Фарм ────────────────────────────────────────────────────────────────

    async def _process_farming(self, db, settings: PipelineSettings) -> None:
        """
        Авто-фарм:
        1. Считаем активные фарм-сессии — проверяем лимит
        2. Находим аккаунты: free, с device_id, level < target_level, не на кулдауне
        3. Устройство не должно быть занято другой задачей
        """
        org_id = settings.org_id

        result = await db.execute(
            select(func.count()).select_from(Task).where(
                Task.org_id == org_id,
                Task.script_id == settings.farming_script_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
        )
        active_count = result.scalar_one()
        if active_count >= settings.max_concurrent_farming:
            return

        slots = settings.max_concurrent_farming - active_count

        # Устройства с активными задачами
        busy_devices_sq = (
            select(Task.device_id)
            .where(
                Task.org_id == org_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
            .scalar_subquery()
        )

        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(GameAccount)
            .where(
                GameAccount.org_id == org_id,
                GameAccount.status == AccountStatus.free,
                GameAccount.device_id.isnot(None),
                GameAccount.device_id.notin_(busy_devices_sq),
                GameAccount.target_level.isnot(None),
                # level < target_level (или level ещё не известен)
                (
                    (GameAccount.level.is_(None))
                    | (GameAccount.level < GameAccount.target_level)
                ),
                # Не на кулдауне
                (
                    (GameAccount.cooldown_until.is_(None))
                    | (GameAccount.cooldown_until <= now)
                ),
            )
            .limit(slots)
        )
        accounts = result.scalars().all()

        for account in accounts:
            try:
                await self._create_farming_task(db, settings, account)
            except Exception as exc:
                logger.error(
                    "orchestration.farm_create_error",
                    account_id=str(account.id),
                    error=str(exc),
                )

    async def _create_farming_task(
        self, db, settings: PipelineSettings, account: GameAccount
    ) -> None:
        """Создать задачу фарма — аккаунт переходит в in_use."""
        account.status = AccountStatus.in_use
        account.status_reason = "Фарм-сессия через оркестратор"
        account.status_changed_at = datetime.now(timezone.utc)

        task = Task(
            org_id=settings.org_id,
            device_id=account.device_id,
            script_id=settings.farming_script_id,
            status=TaskStatus.QUEUED,
            priority=5,
            timeout_seconds=settings.farming_session_duration_seconds,
            input_params={
                "account_id": str(account.id),
                "nickname": account.nickname,
                "password": account.password_encrypted,
                "server_name": account.server_name,
            },
        )
        db.add(task)
        await db.flush()

        await self._enqueue_task(settings.org_id, account.device_id, task.id, task.priority)

        logger.info(
            "orchestration.farm_created",
            account_id=str(account.id),
            nick=account.nickname,
            server=account.server_name,
            device_id=str(account.device_id),
            task_id=str(task.id),
            level=account.level,
            target=account.target_level,
        )

    # ── Обработка завершённых задач ──────────────────────────────────────────

    async def _process_completed_tasks(self, db, settings: PipelineSettings) -> None:
        """
        Обрабатывает завершённые задачи (COMPLETED/FAILED/TIMEOUT) и обновляет
        статусы аккаунтов. После обработки задача помечается CANCELLED, чтобы
        не обрабатываться повторно.

        Регистрация:
          COMPLETED + success=true → аккаунт free (готов к фарму)
          COMPLETED + success=false / FAILED / TIMEOUT → аккаунт disabled

        Фарм:
          COMPLETED → обновить level, если достигнут target → free, иначе cooldown → free
          FAILED с ban_detected → banned (сохраняем device_id + server_name)
          FAILED / TIMEOUT → free (повторная попытка, кулдаун)
        """
        org_id = settings.org_id

        # ── Задачи регистрации ───────────────────────────────────────────────
        if settings.registration_script_id:
            result = await db.execute(
                select(Task).where(
                    Task.org_id == org_id,
                    Task.script_id == settings.registration_script_id,
                    Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT]),
                ).limit(50)
            )
            for task in result.scalars().all():
                account_id = (task.input_params or {}).get("account_id")
                if not account_id:
                    # Помечаем задачу как обработанную
                    task.status = TaskStatus.CANCELLED
                    continue

                res = await db.execute(
                    select(GameAccount).where(GameAccount.id == account_id)
                )
                account = res.scalar_one_or_none()

                # Guard: обрабатываем только pending_registration
                if not account or account.status != AccountStatus.pending_registration:
                    task.status = TaskStatus.CANCELLED
                    continue

                now = datetime.now(timezone.utc)

                if task.status == TaskStatus.COMPLETED:
                    success = (task.result or {}).get("success", False)
                    if success:
                        account.status = AccountStatus.free
                        account.status_reason = "Регистрация завершена успешно"
                        account.registered_at = now
                        account.registration_provider = "auto"
                        self.stats_registrations_completed += 1
                        logger.info(
                            "orchestration.reg_completed",
                            nick=account.nickname,
                            server=account.server_name,
                        )
                    else:
                        error = (task.result or {}).get("error", "unknown")
                        account.status = AccountStatus.disabled
                        account.status_reason = f"Регистрация провалена: {error}"
                        self.stats_registrations_failed += 1
                        logger.warning("orchestration.reg_failed", nick=account.nickname, error=error)
                else:
                    account.status = AccountStatus.disabled
                    account.status_reason = (
                        f"Регистрация {task.status.value}: {task.error_message or 'timeout'}"
                    )
                    self.stats_registrations_failed += 1
                    logger.warning(
                        "orchestration.reg_failed",
                        nick=account.nickname,
                        status=task.status.value,
                    )

                account.status_changed_at = now
                # Помечаем задачу как обработанную
                task.status = TaskStatus.CANCELLED

        # ── Задачи фарма ─────────────────────────────────────────────────────
        if settings.farming_script_id:
            result = await db.execute(
                select(Task).where(
                    Task.org_id == org_id,
                    Task.script_id == settings.farming_script_id,
                    Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT]),
                ).limit(50)
            )
            for task in result.scalars().all():
                account_id = (task.input_params or {}).get("account_id")
                if not account_id:
                    task.status = TaskStatus.CANCELLED
                    continue

                res = await db.execute(
                    select(GameAccount).where(GameAccount.id == account_id)
                )
                account = res.scalar_one_or_none()

                if not account or account.status != AccountStatus.in_use:
                    task.status = TaskStatus.CANCELLED
                    continue

                now = datetime.now(timezone.utc)
                task_result = task.result or {}

                # Обновляем уровень из результата
                new_level = task_result.get("level")
                if new_level is not None:
                    account.level = int(new_level)

                if task.status == TaskStatus.COMPLETED:
                    # Проверяем ban_detected в результате
                    if task_result.get("ban_detected"):
                        self._mark_banned(account, "Бан обнаружен после фарм-сессии", now)
                    # Проверяем достижение целевого уровня
                    elif (
                        account.target_level is not None
                        and account.level is not None
                        and account.level >= account.target_level
                    ):
                        # Целевой уровень достигнут — аккаунт ГОТОВ
                        # device_id и server_name СОХРАНЯЮТСЯ в строке
                        account.status = AccountStatus.free
                        account.status_reason = (
                            f"Целевой уровень {account.target_level} достигнут — готов"
                        )
                        logger.info(
                            "orchestration.farm_target_reached",
                            nick=account.nickname,
                            level=account.level,
                            server=account.server_name,
                        )
                    else:
                        # Нужен ещё фарм — ставим на кулдаун, потом вернётся в free
                        cooldown_min = settings.cooldown_between_sessions_minutes
                        account.status = AccountStatus.cooldown
                        account.status_reason = f"Фарм-сессия #{account.total_sessions + 1} завершена, кулдаун {cooldown_min}мин"
                        account.cooldown_until = now + timedelta(minutes=cooldown_min)

                elif task.status == TaskStatus.FAILED:
                    # Проверяем причину — бан или обычная ошибка
                    error_msg = task.error_message or ""
                    if task_result.get("ban_detected") or "ban" in error_msg.lower():
                        self._mark_banned(account, f"Бан: {error_msg}", now)
                    else:
                        # Обычная ошибка — возвращаем free для повторной попытки, с кулдауном
                        cooldown_min = settings.cooldown_between_sessions_minutes
                        account.status = AccountStatus.cooldown
                        account.status_reason = f"Фарм-ошибка: {error_msg[:200]}, кулдаун {cooldown_min}мин"
                        account.cooldown_until = now + timedelta(minutes=cooldown_min)
                        logger.warning(
                            "orchestration.farm_error",
                            nick=account.nickname,
                            error=error_msg[:200],
                        )

                elif task.status == TaskStatus.TIMEOUT:
                    # Таймаут — вернуть free для повторной попытки
                    cooldown_min = settings.cooldown_between_sessions_minutes
                    account.status = AccountStatus.cooldown
                    account.status_reason = f"Фарм-таймаут, кулдаун {cooldown_min}мин"
                    account.cooldown_until = now + timedelta(minutes=cooldown_min)
                    logger.warning("orchestration.farm_timeout", nick=account.nickname)

                account.status_changed_at = now
                account.total_sessions += 1
                account.last_session_end = now
                task.status = TaskStatus.CANCELLED

    # ── Кулдаун → free ───────────────────────────────────────────────────────

    async def _process_cooldowns(self, db, settings: PipelineSettings) -> None:
        """Аккаунты с истёкшим кулдауном возвращаются в free → готовы к новому фарму."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(GameAccount).where(
                GameAccount.org_id == settings.org_id,
                GameAccount.status == AccountStatus.cooldown,
                GameAccount.cooldown_until.isnot(None),
                GameAccount.cooldown_until <= now,
            ).limit(100)
        )
        for account in result.scalars().all():
            account.status = AccountStatus.free
            account.status_reason = "Кулдаун истёк, готов к следующей фарм-сессии"
            account.status_changed_at = now
            account.cooldown_until = None
            logger.info("orchestration.cooldown_expired", nick=account.nickname)

    # ── Авто-замена забаненных ────────────────────────────────────────────────

    async def _process_ban_replacement(self, db, settings: PipelineSettings) -> None:
        """
        Для каждого забаненного аккаунта, у которого device_id ещё активно
        и на устройстве нет задач — создаём новый аккаунт для регистрации.
        Забаненный аккаунт остаётся как есть (с server_name и device_id).
        """
        if not settings.registration_script_id:
            return

        org_id = settings.org_id

        # Устройства с активными задачами
        busy_devices_sq = (
            select(Task.device_id)
            .where(
                Task.org_id == org_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
            .scalar_subquery()
        )

        # Забаненные аккаунты, у которых device ещё онлайн и свободен
        result = await db.execute(
            select(GameAccount)
            .join(Device, GameAccount.device_id == Device.id)
            .where(
                GameAccount.org_id == org_id,
                GameAccount.status == AccountStatus.banned,
                Device.is_active.is_(True),
                Device.server_name.isnot(None),
                GameAccount.device_id.notin_(busy_devices_sq),
                # Только недавние баны (за последние 24ч) — не бесконечный цикл
                GameAccount.status_changed_at >= datetime.now(timezone.utc) - timedelta(hours=24),
            )
            .options(selectinload(GameAccount.device))
            .limit(5)
        )
        banned_accounts = result.scalars().all()

        for banned in banned_accounts:
            device = banned.device
            if not device:
                continue

            # Отвязываем забаненный аккаунт от устройства
            # (server_name и ban_reason ОСТАЮТСЯ — для истории)
            banned.device_id = None
            banned.assigned_at = None
            banned.status_reason = (
                f"{banned.status_reason or 'Забанен'} | "
                f"Устройство: {device.name}, сервер: {banned.server_name}"
            )

            # Создаём замену — новый аккаунт + задачу регистрации
            try:
                await self._create_registration_task(db, settings, device)
                logger.info(
                    "orchestration.ban_replaced",
                    banned_nick=banned.nickname,
                    device=device.name,
                    server=device.server_name,
                )
            except Exception as exc:
                logger.error(
                    "orchestration.ban_replace_error",
                    banned_nick=banned.nickname,
                    error=str(exc),
                )

    # ── Утилиты ──────────────────────────────────────────────────────────────

    def _mark_banned(self, account: GameAccount, reason: str, now: datetime) -> None:
        """Пометить аккаунт как забаненный — device_id и server_name СОХРАНЯЮТСЯ."""
        account.status = AccountStatus.banned
        account.status_reason = reason
        account.total_bans += 1
        account.last_ban_at = now
        account.ban_reason = reason
        self.stats_bans_detected += 1
        logger.warning(
            "orchestration.ban_detected",
            nick=account.nickname,
            server=account.server_name,
            device_id=str(account.device_id) if account.device_id else None,
            total_bans=account.total_bans,
        )

    @staticmethod
    async def _enqueue_task(org_id, device_id, task_id, priority: int) -> None:
        """Поставить задачу в per-device Redis очередь."""
        from backend.database.redis_client import redis_binary
        from backend.services.task_queue import TaskQueueService

        if redis_binary:
            queue_svc = TaskQueueService(redis_binary)
            await queue_svc.enqueue(
                org_id=str(org_id),
                device_id=str(device_id),
                task_id=str(task_id),
                priority=priority,
            )
