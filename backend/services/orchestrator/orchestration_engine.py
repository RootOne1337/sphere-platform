"""Admit and account for automatic registration and farming tasks."""
from __future__ import annotations

import asyncio
import secrets
import string
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Literal

import structlog
from fastapi import HTTPException
from sqlalchemy import Select, and_, exists, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
from backend.database.tenant import bind_tenant_context
from backend.metrics import orchestration_failures_total
from backend.models.application_automation_policy import ApplicationAutomationPolicy
from backend.models.application_profile import ApplicationProfile
from backend.models.device import Device
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.pipeline_settings import PipelineSettings
from backend.models.script import Script, ScriptVersion
from backend.models.task import ORCHESTRATION_ASSIGNMENT_PARAM, Task, TaskStatus
from backend.services.account_credentials import set_account_password
from backend.services.application_account_scope import resolve_application_account_scope
from backend.services.nick_generator import NickGenerator
from backend.services.task_service import TaskService

logger = structlog.get_logger()
_POLL_INTERVAL = 10.0
_FAILURE_LOG_INTERVAL = 60.0
_DISCOVERY_PAGE_SIZE = 64
_ACTIVE = (TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED)
_LEGACY_TERMINAL = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT)
_TERMINAL = (*_LEGACY_TERMINAL, TaskStatus.CANCELLED)
_SEED_BLOCKERS = (AccountStatus.free, AccountStatus.in_use, AccountStatus.cooldown,
                  AccountStatus.pending_registration, AccountStatus.banned)
_PASSWORD_ALPHABET = string.ascii_letters + string.digits
_PASSWORD_LENGTH = 12

Role = Literal["register", "farm"]
Policy = PipelineSettings | ApplicationAutomationPolicy


class OrchestrationEngine:
    def __init__(self) -> None:
        self._running = False
        self._cursor: uuid.UUID | None = None
        self._next_failure_log: dict[str, float] = {}
        self.stats_registrations_completed = 0
        self.stats_registrations_failed = 0
        self.stats_bans_detected = 0

    async def start(self) -> None:
        self._running = True
        logger.info("orchestration_engine.started")
        while self._running:
            try:
                await self._tick()
            except Exception as exc:
                self._report_failure("discovery", error_type=type(exc).__name__)
            await asyncio.sleep(_POLL_INTERVAL)

    async def stop(self) -> None:
        self._running = False
        logger.info("orchestration_engine.stopped")

    async def _tick(self) -> None:
        async with asyncio.timeout(5), AsyncSessionLocal() as db:
            query = text("SELECT tenant_id FROM sphere_auth.orchestration_work(CAST(:after_org AS uuid))")
            org_ids = (await db.scalars(query, {"after_org": self._cursor})).all()
            if not org_ids and self._cursor is not None:
                org_ids = (await db.scalars(query, {"after_org": None})).all()
        self._cursor = org_ids[-1] if len(org_ids) == _DISCOVERY_PAGE_SIZE else None
        for org_id in org_ids:
            try:
                async with AsyncSessionLocal() as db:
                    await bind_tenant_context(db, str(org_id))
                    await db.execute(text("SET LOCAL statement_timeout = '5s'"))
                    # Keep the same tenant's quotas and legacy/profile admissions
                    # serialized across worker replicas without taking an admin lock.
                    acquired = await db.scalar(text("""
                        SELECT pg_try_advisory_xact_lock(hashtextextended(:scope, 0))
                    """), {"scope": f"automatic-orchestration:{org_id}"})
                    if acquired:
                        await self._process_org(db, org_id)
                        await db.commit()
            except Exception as exc:
                self._report_failure("tenant_processing", org_id=str(org_id), error_type=type(exc).__name__)

    def _report_failure(self, reason: str, **context: str) -> None:
        orchestration_failures_total.labels(reason=reason).inc()
        now = monotonic()
        if now >= self._next_failure_log.get(reason, 0):
            self._next_failure_log[reason] = now + _FAILURE_LOG_INTERVAL
            logger.warning("orchestration_engine.failure", reason=reason, **context)

    async def _process_org(self, db: AsyncSession, org_id: uuid.UUID) -> None:
        settings = await db.scalar(select(PipelineSettings).where(PipelineSettings.org_id == org_id).with_for_update())
        legacy = settings if settings is not None and settings.orchestration_enabled else None
        await self._process_completed_tasks(db, legacy, org_id=org_id)
        await self._process_cooldowns(db, org_id)

        if legacy is not None:
            if legacy.registration_enabled:
                await self._admit(db, legacy, "register", settings=legacy)
            if legacy.farming_enabled:
                await self._admit(db, legacy, "farm", settings=legacy)
            if legacy.ban_detection_enabled and legacy.auto_replace_banned:
                await self._admit(db, legacy, "register", settings=legacy, replace_banned=True)

        policies = (await db.execute(
            select(ApplicationAutomationPolicy, ApplicationProfile)
            .join(ApplicationProfile, and_(
                ApplicationProfile.org_id == org_id,
                ApplicationProfile.id == ApplicationAutomationPolicy.application_profile_id,
            ))
            .where(
                ApplicationAutomationPolicy.org_id == org_id,
                or_(ApplicationAutomationPolicy.registration_enabled, ApplicationAutomationPolicy.farming_enabled),
                ApplicationProfile.android_package.is_not(None),
            )
            .order_by(ApplicationAutomationPolicy.application_profile_id)
            .with_for_update(of=ApplicationAutomationPolicy, skip_locked=True)
        )).all()
        for policy, profile in policies:
            if policy.registration_enabled:
                await self._admit(db, policy, "register", settings=settings, profile=profile)
                if settings is not None and settings.ban_detection_enabled and settings.auto_replace_banned:
                    await self._admit(db, policy, "register", settings=settings, profile=profile, replace_banned=True)
            if policy.farming_enabled:
                await self._admit(db, policy, "farm", settings=settings, profile=profile)

    @staticmethod
    def _script_for(policy: Policy, role: Role) -> uuid.UUID | None:
        return policy.registration_script_id if role == "register" else policy.farming_script_id

    async def _available_slots(
        self, db: AsyncSession, policy: Policy, role: Role, profile: ApplicationProfile | None,
    ) -> int:
        script_id = self._script_for(policy, role)
        if script_id is None:
            return 0
        max_slots = policy.max_concurrent_registrations if role == "register" else policy.max_concurrent_farming
        scope = and_(Task.orchestration_kind == role,
                     Task.orchestration_profile_id == (profile.id if profile is not None else None))
        if profile is None:
            # The old counters included unmarked tasks using this script.
            scope = or_(scope, _legacy_task_scope(script_id))
        active = await db.scalar(select(func.count()).select_from(Task).where(
            Task.org_id == policy.org_id, Task.status.in_(_ACTIVE), scope,
        ))
        return max(0, max_slots - (active or 0))

    @staticmethod
    def _busy_device(org_id: uuid.UUID):
        return exists().where(Task.org_id == org_id, Task.device_id == Device.id, Task.status.in_(_ACTIVE))

    @staticmethod
    def _device_scope(profile: ApplicationProfile | None):
        if profile is None:
            return and_(Device.application_profile_id.is_(None), Device.application_server_key.is_(None))
        return and_(Device.application_profile_id == profile.id,
                    Device.application_server_key.in_([server["key"] for server in profile.servers]))

    @staticmethod
    def _account_scope(org_id: uuid.UUID, profile: ApplicationProfile | None):
        if profile is None:
            # Existing unbound workflows can use arbitrary legacy game strings.
            return ~exists().where(ApplicationProfile.org_id == org_id, ApplicationProfile.key == GameAccount.game)
        server_pairs = [
            and_(Device.application_server_key == server["key"], GameAccount.server_name == server["name"])
            for server in profile.servers
        ]
        return and_(GameAccount.game == profile.key, or_(False, *server_pairs))

    def _registration_candidates(
        self, org_id: uuid.UUID, profile: ApplicationProfile | None,
    ) -> Select[tuple[uuid.UUID]]:
        scope = self._device_scope(profile)
        if profile is None:
            scope = and_(scope, Device.server_name.is_not(None))
        else:
            # Leave a usable or banned account in place so farming or the
            # separately controlled replacement path can handle it.
            has_account = exists().where(
                GameAccount.org_id == org_id, GameAccount.device_id == Device.id,
                GameAccount.status.in_(_SEED_BLOCKERS), self._account_scope(org_id, profile),
            )
            scope = and_(scope, ~has_account)
        return select(Device.id).where(
            Device.org_id == org_id, Device.is_active.is_(True), scope, ~self._busy_device(org_id),
        ).order_by(Device.id)

    def _account_candidates(
        self, org_id: uuid.UUID, profile: ApplicationProfile | None, *, replace_banned: bool,
    ) -> Select[tuple[uuid.UUID, uuid.UUID]]:
        statement = select(Device.id, GameAccount.id).join(Device, GameAccount.device_id == Device.id).where(
            Device.org_id == org_id, Device.is_active.is_(True), GameAccount.org_id == org_id,
            self._device_scope(profile), self._account_scope(org_id, profile), ~self._busy_device(org_id),
            *self._account_eligibility(org_id, profile, replace_banned),
        )
        # A single device can have multiple eligible accounts, but consumes one slot.
        return statement.distinct(Device.id).order_by(Device.id, GameAccount.id)

    @staticmethod
    def _account_eligibility(org_id: uuid.UUID, profile: ApplicationProfile | None, replace_banned: bool):
        now = datetime.now(timezone.utc)
        if replace_banned:
            banned = (
                GameAccount.status == AccountStatus.banned,
                GameAccount.status_changed_at >= now - timedelta(hours=24),
            )
            if profile is None:
                return (*banned, Device.server_name.is_not(None))
            other = GameAccount.__table__.alias("replacement_account")
            has_replacement = exists(select(1).select_from(other).where(
                other.c.org_id == org_id, other.c.device_id == Device.id,
                other.c.game == profile.key, other.c.server_name == GameAccount.server_name,
                other.c.status.in_(_SEED_BLOCKERS[:-1]),
            ))
            return (*banned, ~has_replacement)
        return (
            GameAccount.status == AccountStatus.free, GameAccount.target_level.is_not(None),
            or_(GameAccount.level.is_(None), GameAccount.level < GameAccount.target_level),
            or_(GameAccount.cooldown_until.is_(None), GameAccount.cooldown_until <= now),
        )

    async def _admit(
        self, db: AsyncSession, policy: Policy, role: Role, *, settings: PipelineSettings | None,
        profile: ApplicationProfile | None = None, replace_banned: bool = False,
    ) -> None:
        slots = await self._available_slots(db, policy, role, profile)
        script_id = self._script_for(policy, role)
        if not slots or script_id is None:
            return
        org_id = policy.org_id
        version = await db.scalar(select(Script.current_version_id).join(ScriptVersion, and_(
            ScriptVersion.id == Script.current_version_id, ScriptVersion.script_id == Script.id,
            ScriptVersion.org_id == org_id,
        )).where(Script.id == script_id, Script.org_id == org_id, Script.is_archived.is_(False)))
        if version is None:
            self._report_failure(
                "script_unavailable", org_id=str(org_id), role=role, script_id=str(script_id),
                profile_id=str(profile.id) if profile is not None else "legacy",
            )
            return

        candidates: Sequence[tuple[uuid.UUID, uuid.UUID | None]]
        if role == "register" and not replace_banned:
            devices = await db.scalars(self._registration_candidates(org_id, profile).limit(slots))
            candidates = [(device_id, None) for device_id in devices]
        else:
            cap = min(slots, 5) if replace_banned else slots
            candidates = (await db.execute(
                self._account_candidates(org_id, profile, replace_banned=replace_banned).limit(cap)
            )).tuples().all()

        for device_id, account_id in candidates:
            try:
                async with db.begin_nested():
                    await self._admit_candidate(
                        db, policy, role, settings, profile, device_id, account_id, script_id, version,
                    )
            except HTTPException as exc:
                if exc.status_code not in {404, 409}:
                    raise
                logger.debug("orchestration.candidate_changed", org_id=str(org_id), device_id=str(device_id),
                            role=role, status_code=exc.status_code)
            except IntegrityError as exc:
                if getattr(exc.orig, "sqlstate", None) != "23505":
                    raise
                logger.debug("orchestration.candidate_conflict", org_id=str(org_id), device_id=str(device_id),
                            role=role)

    async def _admit_candidate(
        self, db: AsyncSession, policy: Policy, role: Role, settings: PipelineSettings | None,
        profile: ApplicationProfile | None, device_id: uuid.UUID, account_id: uuid.UUID | None,
        script_id: uuid.UUID, version: uuid.UUID,
    ) -> None:
        org_id = policy.org_id
        device = await db.scalar(select(Device).where(
            Device.id == device_id, Device.org_id == org_id, Device.is_active.is_(True),
            self._device_scope(profile),
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))
        if device is None or await db.scalar(select(self._busy_device(org_id)).select_from(Device).where(
            Device.id == device_id,
        )):
            return
        scope = await resolve_application_account_scope(db, device)
        if profile is None:
            game, server_name = "black_russia", device.server_name
        elif scope is not None and scope[0] == profile.key:
            game, server_name = scope
        else:
            return

        account = None
        if account_id is not None:
            # Recheck account eligibility after serializing with device binding.
            account = await db.scalar(select(GameAccount).join(Device, Device.id == GameAccount.device_id).where(
                Device.id == device_id, GameAccount.id == account_id, GameAccount.org_id == org_id,
                self._account_scope(org_id, profile), *self._account_eligibility(org_id, profile, role == "register"),
            ).with_for_update(of=GameAccount, skip_locked=True).execution_options(populate_existing=True))
            if account is None or (profile is not None and (account.game, account.server_name) != (game, server_name)):
                return

        replaced = None
        if role == "register":
            if server_name is None:
                return
            if account_id is None and profile is not None:
                candidate = await db.scalar(self._registration_candidates(org_id, profile).where(Device.id == device_id))
                if candidate is None:
                    return
            replaced = account
            account = await self._create_registration_account(db, policy, settings, device, game, server_name)
        if account is None:
            return

        task = await TaskService(db).create_task(
            org_id=org_id, device_id=device.id, script_id=script_id, script_version_id=version,
            expected_current_version_id=version, account_id=account.id, priority=10 if role == "register" else 5,
            input_params={ORCHESTRATION_ASSIGNMENT_PARAM: _assignment_timestamp(account)},
        )
        task.orchestration_kind = role
        task.orchestration_profile_id = profile.id if profile is not None else None
        if role == "register":
            task.timeout_seconds = policy.registration_timeout_seconds
            if replaced is not None:
                replaced.device_id = None
                replaced.assigned_at = None
                replaced.status_reason = (
                    f"{replaced.status_reason or 'Забанен'} | "
                    f"Устройство: {device.name}, сервер: {replaced.server_name}"
                )
        else:
            task.timeout_seconds = policy.farming_session_duration_seconds
            task.orchestration_cooldown_minutes = policy.cooldown_between_sessions_minutes
            account.status = AccountStatus.in_use
            account.status_reason = "Фарм-сессия через оркестратор"
            account.status_changed_at = datetime.now(timezone.utc)
        await db.flush()
        logger.debug("orchestration.task_admitted", org_id=str(org_id), role=role, task_id=str(task.id),
                    profile_id=str(profile.id) if profile is not None else None)

    @staticmethod
    async def _create_registration_account(
        db: AsyncSession, policy: Policy, settings: PipelineSettings | None, device: Device,
        game: str, server_name: str,
    ) -> GameAccount:
        pattern = (settings.nick_pattern if settings is not None and settings.nick_generation_enabled
                   else "{first_name}_{last_name}")
        nickname = await NickGenerator(db).generate(org_id=str(policy.org_id), pattern=pattern)
        now = datetime.now(timezone.utc)
        account = GameAccount(
            org_id=policy.org_id, game=game, login=nickname, nickname=nickname,
            server_name=server_name, device_id=device.id, assigned_at=now, target_level=policy.default_target_level,
            status=AccountStatus.pending_registration, status_changed_at=now,
            status_reason="Авто-регистрация через оркестратор",
        )
        set_account_password(account, "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(_PASSWORD_LENGTH)))
        db.add(account)
        await db.flush()
        return account

    async def _process_completed_tasks(
        self, db: AsyncSession, settings: PipelineSettings | None, *, org_id: uuid.UUID | None = None,
    ) -> None:
        if org_id is None:
            if settings is None:
                raise ValueError("Organization required for orchestration accounting")
            org_id = settings.org_id
        for role in ("register", "farm"):
            scope = and_(Task.orchestration_kind == role, Task.status.in_(_TERMINAL))
            script_id = self._script_for(settings, role) if settings is not None else None
            if script_id is not None:
                scope = or_(scope, and_(_legacy_task_scope(script_id), Task.status.in_(_LEGACY_TERMINAL)))
            tasks = await db.scalars(select(Task).where(
                Task.org_id == org_id, Task.orchestration_processed_at.is_(None), scope,
            ).order_by(Task.id).limit(50).with_for_update(skip_locked=True))
            for task in tasks:
                account = await self._completion_account(db, task)
                now = datetime.now(timezone.utc)
                if (role == "register" and task.orchestration_kind is None and settings is not None
                        and task.script_id == settings.farming_script_id and account is not None
                        and account.status == AccountStatus.in_use):
                    # Old rows have no role marker. If both legacy roles use
                    # the script, the admitted account state identifies farm.
                    continue
                if role == "register" and account is not None and account.status == AccountStatus.pending_registration:
                    self._complete_registration(task, account, now)
                elif role == "farm" and account is not None and account.status == AccountStatus.in_use:
                    cooldown = task.orchestration_cooldown_minutes
                    if cooldown is None:
                        cooldown = settings.cooldown_between_sessions_minutes if settings is not None else 30
                    self._complete_farming(task, account, cooldown, now)
                task.orchestration_processed_at = now

    @staticmethod
    async def _completion_account(db: AsyncSession, task: Task) -> GameAccount | None:
        try:
            account_id = uuid.UUID(str((task.input_params or {}).get("account_id")))
        except ValueError:
            return None
        account = await db.scalar(select(GameAccount).where(
            GameAccount.id == account_id, GameAccount.org_id == task.org_id,
        ).with_for_update().execution_options(populate_existing=True))
        if account is not None and task.orchestration_kind is not None:
            if (account.device_id != task.device_id or ORCHESTRATION_ASSIGNMENT_PARAM not in task.input_params
                    or task.input_params[ORCHESTRATION_ASSIGNMENT_PARAM] != _assignment_timestamp(account)):
                return None
        return account

    def _complete_registration(self, task: Task, account: GameAccount, now: datetime) -> None:
        result = task.result if isinstance(task.result, dict) else {}
        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and result.get("ban_detected") is True:
            self._mark_banned(account, "Бан обнаружен при регистрации", now)
            self.stats_registrations_failed += 1
            return
        if task.status == TaskStatus.COMPLETED and result.get("success"):
            account.status = AccountStatus.free
            account.status_reason = "Регистрация завершена успешно"
            account.registered_at = now
            account.registration_provider = "auto"
            self.stats_registrations_completed += 1
        else:
            account.status = AccountStatus.disabled
            reason = result.get("error") or task.error_message
            account.status_reason = f"Регистрация завершена без успеха ({task.status})"
            if isinstance(reason, str):
                account.status_reason += f": {reason[:200]}"
            self.stats_registrations_failed += 1
        account.status_changed_at = now

    def _complete_farming(self, task: Task, account: GameAccount, cooldown: int, now: datetime) -> None:
        result = task.result if isinstance(task.result, dict) else {}
        new_level = result.get("level")
        if task.status != TaskStatus.CANCELLED and isinstance(new_level, (str, int, float)) and not isinstance(new_level, bool):
            try:
                level = int(new_level)
                if 0 <= level <= 2_147_483_647:
                    account.level = level
            except (ValueError, OverflowError):
                pass
        if (task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED} and result.get("ban_detected")
                or task.status == TaskStatus.FAILED and "ban" in (task.error_message or "").lower()):
            self._mark_banned(account, "Бан обнаружен после фарм-сессии", now)
        elif (task.status == TaskStatus.COMPLETED and account.target_level is not None
                and account.level is not None and account.level >= account.target_level):
            account.status = AccountStatus.free
            account.status_reason = f"Целевой уровень {account.target_level} достигнут — готов"
            account.cooldown_until = None
        else:
            account.status = AccountStatus.cooldown
            account.status_reason = f"Фарм-сессия завершена ({task.status}), кулдаун {cooldown}мин"
            account.cooldown_until = now + timedelta(minutes=cooldown)
        account.status_changed_at = now
        account.total_sessions += 1
        account.last_session_end = now

    @staticmethod
    async def _process_cooldowns(db: AsyncSession, org_id: uuid.UUID) -> None:
        now = datetime.now(timezone.utc)
        accounts = await db.scalars(select(GameAccount).where(
            GameAccount.org_id == org_id, GameAccount.status == AccountStatus.cooldown,
            GameAccount.cooldown_until <= now,
        ).order_by(GameAccount.cooldown_until, GameAccount.id).limit(100).with_for_update(skip_locked=True))
        for account in accounts:
            account.status = AccountStatus.free
            account.status_reason = "Кулдаун истёк, готов к следующей фарм-сессии"
            account.status_changed_at = now
            account.cooldown_until = None

    def _mark_banned(self, account: GameAccount, reason: str, now: datetime) -> None:
        account.status = AccountStatus.banned
        account.status_reason = reason
        account.total_bans += 1
        account.last_ban_at = now
        account.ban_reason = reason
        self.stats_bans_detected += 1
        logger.warning("orchestration.ban_detected", account_id=str(account.id))


def _assignment_timestamp(account: GameAccount) -> str | None:
    return account.assigned_at.astimezone(timezone.utc).isoformat() if account.assigned_at is not None else None


def _legacy_task_scope(script_id: uuid.UUID):
    # A manual rerun can retain the account and original parameters but has
    # no orchestration kind and must not inherit the AUTO accounting role.
    return and_(Task.orchestration_kind.is_(None), Task.script_id == script_id,
                ~Task.input_params.has_key(ORCHESTRATION_ASSIGNMENT_PARAM))
