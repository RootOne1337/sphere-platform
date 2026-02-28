# backend/api/v1/schedules/router.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. Schedule REST API.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# ARCH-3: register_startup регистрирует SchedulerEngine.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.schedule import (
    CreateScheduleRequest,
    ScheduleExecutionListResponse,
    ScheduleExecutionResponse,
    ScheduleListResponse,
    ScheduleResponse,
    UpdateScheduleRequest,
)
from backend.services.scheduler.schedule_service import ScheduleService

logger = structlog.get_logger()

router = APIRouter(prefix="/schedules", tags=["schedules"])


# ── DI фабрики ────────────────────────────────────────────────────────────────


def get_schedule_service(db: AsyncSession = Depends(get_db)) -> ScheduleService:
    return ScheduleService(db)


# ── Startup: запустить SchedulerEngine ───────────────────────────────────────


async def _startup_scheduler_engine() -> None:
    """Запуск фонового loop расписаний."""
    import asyncio

    from backend.services.scheduler.scheduler_engine import SchedulerEngine

    engine = SchedulerEngine()
    task = asyncio.create_task(engine.start())
    logger.info("scheduler_engine.registered")

    async def _shutdown_scheduler_engine() -> None:
        """Graceful-остановка loop расписаний."""
        task.cancel()
        await engine.stop()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("scheduler_engine.stopped")

    register_shutdown("scheduler_engine", _shutdown_scheduler_engine)


register_startup("scheduler_engine", _startup_scheduler_engine)


# ══════════════════════════════════════════════════════════════════════════════
#  Schedule CRUD
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "",
    response_model=ScheduleListResponse,
    summary="Список расписаний",
)
async def list_schedules(
    is_active: bool | None = None,
    target_type: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("schedule:read"),
    svc: ScheduleService = Depends(get_schedule_service),
) -> ScheduleListResponse:
    items, total = await svc.list_schedules(
        org_id=current_user.org_id,
        is_active=is_active,
        target_type=target_type,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return ScheduleListResponse(
        items=[ScheduleResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=ScheduleResponse,
    status_code=201,
    summary="Создать расписание",
)
async def create_schedule(
    body: CreateScheduleRequest,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    # Извлечь поля, передаваемые в модель
    fields = body.model_dump(exclude_unset=False)
    schedule = await svc.create(
        org_id=current_user.org_id,
        created_by_id=current_user.id,
        **fields,
    )
    await db.commit()
    return ScheduleResponse.model_validate(schedule)


@router.get(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Получить расписание по ID",
)
async def get_schedule(
    schedule_id: uuid.UUID,
    current_user: User = require_permission("schedule:read"),
    svc: ScheduleService = Depends(get_schedule_service),
) -> ScheduleResponse:
    schedule = await svc.get(schedule_id, current_user.org_id)
    return ScheduleResponse.model_validate(schedule)


@router.patch(
    "/{schedule_id}",
    response_model=ScheduleResponse,
    summary="Обновить расписание",
)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: UpdateScheduleRequest,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    update_data = body.model_dump(exclude_unset=True)
    schedule = await svc.update(schedule_id, current_user.org_id, **update_data)
    await db.commit()
    return ScheduleResponse.model_validate(schedule)


@router.delete(
    "/{schedule_id}",
    status_code=204,
    response_model=None,
    summary="Деактивировать расписание",
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    await svc.delete(schedule_id, current_user.org_id)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Управление расписанием
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/{schedule_id}/toggle",
    response_model=ScheduleResponse,
    summary="Включить / выключить расписание",
)
async def toggle_schedule(
    schedule_id: uuid.UUID,
    active: bool = Query(..., description="true=включить, false=выключить"),
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    schedule = await svc.toggle(schedule_id, current_user.org_id, active)
    await db.commit()
    return ScheduleResponse.model_validate(schedule)


@router.post(
    "/{schedule_id}/fire-now",
    response_model=ScheduleResponse,
    summary="Принудительно запустить расписание сейчас",
)
async def fire_schedule_now(
    schedule_id: uuid.UUID,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    schedule = await svc.fire_now(schedule_id, current_user.org_id)
    await db.commit()
    return ScheduleResponse.model_validate(schedule)


# ══════════════════════════════════════════════════════════════════════════════
#  Schedule Executions — история срабатываний
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/{schedule_id}/executions",
    response_model=ScheduleExecutionListResponse,
    summary="История срабатываний расписания",
)
async def list_schedule_executions(
    schedule_id: uuid.UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("schedule:read"),
    svc: ScheduleService = Depends(get_schedule_service),
) -> ScheduleExecutionListResponse:
    items, total = await svc.list_executions(
        schedule_id=schedule_id,
        org_id=current_user.org_id,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return ScheduleExecutionListResponse(
        items=[ScheduleExecutionResponse.model_validate(e) for e in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )
