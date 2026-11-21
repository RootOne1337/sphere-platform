# backend/api/v1/schedules/router.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-5. Schedule REST API.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# ARCH-3: register_startup регистрирует SchedulerEngine.
from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header, Query
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.schedule import (
    CreateScheduleRequest,
    ScheduleExecutionListResponse,
    ScheduleFireResponse,
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
    await db.refresh(schedule, ["updated_at"])
    snapshot = ScheduleResponse.model_validate(schedule)
    await db.commit()
    return snapshot


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
    responses={409: {"description": "schedule_revision_conflict"}},
)
async def update_schedule(
    schedule_id: uuid.UUID,
    body: UpdateScheduleRequest,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    update_data = body.model_dump(exclude_unset=True, exclude={"expected_updated_at"})
    schedule = await svc.update(
        schedule_id, current_user.org_id, expected_updated_at=body.expected_updated_at, **update_data,
    )
    await db.refresh(schedule, ["updated_at"])
    snapshot = ScheduleResponse.model_validate(schedule)
    await db.commit()
    return snapshot


@router.delete(
    "/{schedule_id}",
    status_code=204,
    response_model=None,
    summary="Деактивировать расписание",
    responses={409: {"description": "schedule_revision_conflict"}},
)
async def delete_schedule(
    schedule_id: uuid.UUID,
    expected_updated_at: Annotated[AwareDatetime | None, Query(description="Optional ScheduleResponse revision")] = None,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    await svc.delete(schedule_id, current_user.org_id, expected_updated_at=expected_updated_at)
    await db.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  Управление расписанием
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/{schedule_id}/toggle",
    response_model=ScheduleResponse,
    summary="Включить / выключить расписание",
    responses={409: {"description": "schedule_revision_conflict"}},
)
async def toggle_schedule(
    schedule_id: uuid.UUID,
    active: bool = Query(..., description="true=включить, false=выключить"),
    expected_updated_at: Annotated[AwareDatetime | None, Query(description="Optional ScheduleResponse revision")] = None,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
) -> ScheduleResponse:
    schedule = await svc.toggle(schedule_id, current_user.org_id, active, expected_updated_at=expected_updated_at)
    await db.refresh(schedule, ["updated_at"])
    snapshot = ScheduleResponse.model_validate(schedule)
    await db.commit()
    return snapshot


@router.post(
    "/{schedule_id}/fire-now",
    response_model=ScheduleFireResponse,
    summary="Запросить ближайшее срабатывание активного расписания",
    responses={
        409: {"description": "Расписание выключено, вне окна, исчерпало лимит или schedule_revision_conflict"},
        429: {"description": "Достигнут суточный предел ключей повторов расписания"},
    },
)
async def fire_schedule_now(
    schedule_id: uuid.UUID,
    current_user: User = require_permission("schedule:write"),
    svc: ScheduleService = Depends(get_schedule_service),
    db: AsyncSession = Depends(get_db),
    request_key: Annotated[uuid.UUID | None, Header(alias="Idempotency-Key")] = None,
    expected_updated_at: Annotated[AwareDatetime | None, Query(description="Optional ScheduleResponse revision")] = None,
) -> ScheduleFireResponse:
    schedule, requested_fire_at, request_replayed = await svc.request_fire(
        schedule_id, current_user.org_id, request_key, expected_updated_at=expected_updated_at,
    )
    await db.refresh(schedule, ["updated_at"])
    snapshot = ScheduleResponse.model_validate(schedule)
    await db.commit()
    return ScheduleFireResponse(**snapshot.model_dump(), requested_fire_at=requested_fire_at, request_replayed=request_replayed)


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
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )
