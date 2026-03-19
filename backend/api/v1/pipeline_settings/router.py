# backend/api/v1/pipeline_settings/router.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# REST API для управления настройками оркестрации.
# GET  /pipeline-settings         — получить текущие настройки
# PATCH /pipeline-settings        — обновить настройки (partial)
# POST /pipeline-settings/toggle/orchestration  — вкл/выкл оркестрацию
# POST /pipeline-settings/toggle/scheduler      — вкл/выкл планировщик
# POST /pipeline-settings/toggle/registration   — вкл/выкл регистрацию
# POST /pipeline-settings/toggle/farming        — вкл/выкл фарм
# GET  /pipeline-settings/status                — текущий runtime-статус
# GET  /pipeline-settings/servers               — список серверов
# POST /pipeline-settings/nick/generate         — генерация никнеймов
# POST /pipeline-settings/nick/check            — проверка ника
from __future__ import annotations

import json
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.device import Device
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.task import Task, TaskStatus
from backend.models.user import User
from backend.schemas.pipeline_settings import (
    NickCheckRequest,
    NickCheckResponse,
    NickGenerateRequest,
    NickGenerateResponse,
    OrchestrationStatusResponse,
    PipelineSettingsResponse,
    ServerInfo,
    ToggleRequest,
    UpdatePipelineSettingsRequest,
)
from backend.services.nick_generator import NickGenerator
from backend.services.pipeline_settings_service import PipelineSettingsService

logger = structlog.get_logger()

router = APIRouter(prefix="/pipeline-settings", tags=["pipeline-settings"])


def get_settings_service(db: AsyncSession = Depends(get_db)) -> PipelineSettingsService:
    return PipelineSettingsService(db)


# ── GET — Получить настройки ─────────────────────────────────────────────────


@router.get(
    "",
    response_model=PipelineSettingsResponse,
    summary="Получить настройки оркестрации",
)
async def get_settings(
    current_user: User = require_permission("pipeline:read"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineSettingsResponse:
    """Возвращает персистентные настройки оркестрации для организации."""
    settings = await svc.get_or_create(current_user.org_id)
    await db.commit()
    await db.refresh(settings)
    return PipelineSettingsResponse.model_validate(settings)


# ── PATCH — Обновить настройки ───────────────────────────────────────────────


@router.patch(
    "",
    response_model=PipelineSettingsResponse,
    summary="Обновить настройки оркестрации (partial update)",
)
async def update_settings(
    body: UpdatePipelineSettingsRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineSettingsResponse:
    """Частичное обновление настроек. Передавай только те поля, которые хочешь изменить."""
    updates = body.model_dump(exclude_unset=True)
    settings = await svc.update(current_user.org_id, updates)
    await db.commit()
    await db.refresh(settings)
    logger.info(
        "pipeline_settings.api_updated",
        user_id=str(current_user.id),
        fields=list(updates.keys()),
    )
    return PipelineSettingsResponse.model_validate(settings)


# ── Toggle endpoints ─────────────────────────────────────────────────────────


@router.post(
    "/toggle/orchestration",
    response_model=PipelineSettingsResponse,
    summary="Вкл/выкл оркестрацию",
)
async def toggle_orchestration(
    body: ToggleRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineSettingsResponse:
    """Переключить глобальную оркестрацию. Сохраняется после перезагрузки."""
    settings = await svc.toggle_orchestration(current_user.org_id, body.enabled)
    await db.commit()
    await db.refresh(settings)
    logger.info("orchestration.toggled", enabled=body.enabled, user=str(current_user.id))
    return PipelineSettingsResponse.model_validate(settings)


@router.post(
    "/toggle/scheduler",
    response_model=PipelineSettingsResponse,
    summary="Вкл/выкл планировщик задач",
)
async def toggle_scheduler(
    body: ToggleRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineSettingsResponse:
    """Переключить планировщик задач. Сохраняется после перезагрузки."""
    settings = await svc.toggle_scheduler(current_user.org_id, body.enabled)
    await db.commit()
    await db.refresh(settings)
    logger.info("scheduler.toggled", enabled=body.enabled, user=str(current_user.id))
    return PipelineSettingsResponse.model_validate(settings)


@router.post(
    "/toggle/registration",
    response_model=PipelineSettingsResponse,
    summary="Вкл/выкл авто-регистрацию",
)
async def toggle_registration(
    body: ToggleRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineSettingsResponse:
    """Переключить автоматическую регистрацию аккаунтов."""
    settings = await svc.toggle_registration(current_user.org_id, body.enabled)
    await db.commit()
    await db.refresh(settings)
    return PipelineSettingsResponse.model_validate(settings)


@router.post(
    "/toggle/farming",
    response_model=PipelineSettingsResponse,
    summary="Вкл/выкл авто-фарм",
)
async def toggle_farming(
    body: ToggleRequest,
    current_user: User = require_permission("pipeline:write"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> PipelineSettingsResponse:
    """Переключить автоматический фарм."""
    settings = await svc.toggle_farming(current_user.org_id, body.enabled)
    await db.commit()
    await db.refresh(settings)
    return PipelineSettingsResponse.model_validate(settings)


# ── Статус оркестрации (runtime) ─────────────────────────────────────────────


@router.get(
    "/status",
    response_model=OrchestrationStatusResponse,
    summary="Текущий статус оркестрации (runtime)",
)
async def get_orchestration_status(
    current_user: User = require_permission("pipeline:read"),
    svc: PipelineSettingsService = Depends(get_settings_service),
    db: AsyncSession = Depends(get_db),
) -> OrchestrationStatusResponse:
    """Возвращает текущее состояние оркестрации с live-данными из БД."""
    settings = await svc.get_or_create(current_user.org_id)
    org_id = current_user.org_id

    # Подсчёт активных регистраций (RUNNING + QUEUED задачи с registration_script_id)
    active_reg = 0
    if settings.registration_script_id:
        result = await db.execute(
            select(func.count()).select_from(Task).where(
                Task.org_id == org_id,
                Task.script_id == settings.registration_script_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
        )
        active_reg = result.scalar_one()

    # Подсчёт активных фарм-сессий
    active_farm = 0
    if settings.farming_script_id:
        result = await db.execute(
            select(func.count()).select_from(Task).where(
                Task.org_id == org_id,
                Task.script_id == settings.farming_script_id,
                Task.status.in_([TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            )
        )
        active_farm = result.scalar_one()

    # Аккаунты в pending_registration
    result = await db.execute(
        select(func.count()).select_from(GameAccount).where(
            GameAccount.org_id == org_id,
            GameAccount.status == AccountStatus.pending_registration,
        )
    )
    pending_reg = result.scalar_one()

    # Устройства с привязанным сервером
    result = await db.execute(
        select(func.count()).select_from(Device).where(
            Device.org_id == org_id,
            Device.server_name.isnot(None),
            Device.is_active.is_(True),
        )
    )
    devices_with_server = result.scalar_one()

    # Свободные аккаунты
    result = await db.execute(
        select(func.count()).select_from(GameAccount).where(
            GameAccount.org_id == org_id,
            GameAccount.status == AccountStatus.free,
        )
    )
    free_accounts = result.scalar_one()

    # Забаненные аккаунты
    result = await db.execute(
        select(func.count()).select_from(GameAccount).where(
            GameAccount.org_id == org_id,
            GameAccount.status == AccountStatus.banned,
        )
    )
    banned_accounts = result.scalar_one()

    await db.commit()

    return OrchestrationStatusResponse(
        orchestration_enabled=settings.orchestration_enabled,
        scheduler_enabled=settings.scheduler_enabled,
        registration_enabled=settings.registration_enabled,
        farming_enabled=settings.farming_enabled,
        active_registrations=active_reg,
        active_farming_sessions=active_farm,
        pending_registrations=pending_reg,
        total_devices_with_server=devices_with_server,
        total_free_accounts=free_accounts,
        total_banned_accounts=banned_accounts,
    )


# ── Серверы ──────────────────────────────────────────────────────────────────


def _load_servers() -> list[ServerInfo]:
    """Загрузить список серверов из servers.json (кэшируется в памяти модуля)."""
    config_path = Path(__file__).resolve().parents[3] / "core" / "servers.json"
    if not config_path.exists():
        logger.warning("servers.json не найден: %s", config_path)
        return []
    with open(config_path, encoding="utf-8") as f:
        raw = json.load(f)
    return [ServerInfo(**s) for s in raw]


_SERVERS_CACHE: list[ServerInfo] | None = None


@router.get(
    "/servers",
    response_model=list[ServerInfo],
    summary="Список доступных игровых серверов",
)
async def list_servers(
    current_user: User = require_permission("pipeline:read"),
) -> list[ServerInfo]:
    """Возвращает список всех игровых серверов из servers.json."""
    global _SERVERS_CACHE
    if _SERVERS_CACHE is None:
        _SERVERS_CACHE = _load_servers()
    return _SERVERS_CACHE


# ── Генерация ников ──────────────────────────────────────────────────────────


@router.post(
    "/nick/generate",
    response_model=NickGenerateResponse,
    summary="Сгенерировать уникальные никнеймы",
)
async def generate_nicks(
    body: NickGenerateRequest,
    current_user: User = require_permission("pipeline:write"),
    db: AsyncSession = Depends(get_db),
) -> NickGenerateResponse:
    """Генерация уникальных никнеймов с проверкой уникальности в БД."""
    gen = NickGenerator(db)
    nicks = await gen.generate_batch(
        org_id=str(current_user.org_id),
        count=body.count,
        pattern=body.pattern,
        gender=body.gender,
    )
    return NickGenerateResponse(nicknames=nicks)


@router.post(
    "/nick/check",
    response_model=NickCheckResponse,
    summary="Проверить доступность никнейма",
)
async def check_nick(
    body: NickCheckRequest,
    current_user: User = require_permission("pipeline:read"),
    db: AsyncSession = Depends(get_db),
) -> NickCheckResponse:
    """Проверить, свободен ли никнейм в рамках организации."""
    gen = NickGenerator(db)
    available = await gen.is_nickname_available(
        org_id=str(current_user.org_id),
        nickname=body.nickname,
    )
    return NickCheckResponse(nickname=body.nickname, available=available)
