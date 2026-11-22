# backend/api/v1/event_triggers/router.py
# ВЛАДЕЛЕЦ: TZ-11+ Event Triggers REST API.
# CRUD + toggle для управления автоматическими реакциями на события.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.core.rbac import has_permission
from backend.database.engine import get_db
from backend.models.device_event import DeviceEvent
from backend.models.event_trigger import EventTrigger
from backend.models.pipeline import Pipeline
from backend.models.user import User
from backend.schemas.event_trigger import (
    CreateEventTriggerRequest,
    EventTriggerListResponse,
    EventTriggerResponse,
    EventTriggerSimulationResponse,
    UpdateEventTriggerRequest,
)
from backend.services.event_trigger_admission import simulate_trigger

logger = structlog.get_logger()

router = APIRouter(prefix="/event-triggers", tags=["event-triggers"])


async def _require_active_pipeline(db: AsyncSession, org_id: uuid.UUID, pipeline_id: uuid.UUID) -> None:
    pipeline = await db.scalar(select(Pipeline).where(
        Pipeline.id == pipeline_id, Pipeline.org_id == org_id,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline не найден")
    if not pipeline.is_active:
        raise HTTPException(status_code=409, detail="Пайплайн отключён. Выберите активный пайплайн.")


# ══════════════════════════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "",
    response_model=EventTriggerListResponse,
    summary="Список EventTrigger'ов с фильтрацией",
)
async def list_event_triggers(
    is_active: bool | None = None,
    event_type_pattern: str | None = None,
    pipeline_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("pipeline:read"),
    db: AsyncSession = Depends(get_db),
) -> EventTriggerListResponse:
    base = select(EventTrigger).where(EventTrigger.org_id == current_user.org_id)
    count_q = select(func.count()).select_from(EventTrigger).where(
        EventTrigger.org_id == current_user.org_id,
    )

    if is_active is not None:
        base = base.where(EventTrigger.is_active == is_active)
        count_q = count_q.where(EventTrigger.is_active == is_active)
    if event_type_pattern:
        base = base.where(EventTrigger.event_type_pattern == event_type_pattern)
        count_q = count_q.where(EventTrigger.event_type_pattern == event_type_pattern)
    if pipeline_id:
        base = base.where(EventTrigger.pipeline_id == pipeline_id)
        count_q = count_q.where(EventTrigger.pipeline_id == pipeline_id)

    total = (await db.execute(count_q)).scalar() or 0
    items = (
        await db.execute(
            base.order_by(EventTrigger.created_at.desc(), EventTrigger.id.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return EventTriggerListResponse(
        items=[EventTriggerResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.post(
    "",
    response_model=EventTriggerResponse,
    status_code=201,
    summary="Создать EventTrigger",
)
async def create_event_trigger(
    body: CreateEventTriggerRequest,
    current_user: User = require_permission("pipeline:write"),
    db: AsyncSession = Depends(get_db),
) -> EventTriggerResponse:
    await _require_active_pipeline(db, current_user.org_id, body.pipeline_id)

    trigger = EventTrigger(
        org_id=current_user.org_id,
        name=body.name,
        description=body.description,
        event_type_pattern=body.event_type_pattern,
        pipeline_id=body.pipeline_id,
        input_params_template=body.input_params_template,
        cooldown_seconds=body.cooldown_seconds,
        max_triggers_per_hour=body.max_triggers_per_hour,
    )
    db.add(trigger)
    await db.commit()
    await db.refresh(trigger)

    logger.info(
        "event_trigger.created",
        trigger_id=str(trigger.id),
        name=trigger.name,
        pattern=trigger.event_type_pattern,
        pipeline_id=str(trigger.pipeline_id),
    )
    return EventTriggerResponse.model_validate(trigger)


@router.get(
    "/{trigger_id}",
    response_model=EventTriggerResponse,
    summary="Получить EventTrigger по ID",
)
async def get_event_trigger(
    trigger_id: uuid.UUID,
    current_user: User = require_permission("pipeline:read"),
    db: AsyncSession = Depends(get_db),
) -> EventTriggerResponse:
    trigger = await db.get(EventTrigger, trigger_id)
    if not trigger or trigger.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")
    return EventTriggerResponse.model_validate(trigger)


@router.get(
    "/{trigger_id}/simulate",
    response_model=EventTriggerSimulationResponse,
    summary="Оценить сохранённый триггер по типу или сохранённому событию без запуска",
)
async def simulate_event_trigger(
    trigger_id: uuid.UUID,
    response: Response,
    event_type: str | None = Query(None, min_length=1, max_length=200, pattern=r"\S"),
    event_id: uuid.UUID | None = Query(None),
    current_user: User = require_permission("pipeline:read"),
    db: AsyncSession = Depends(get_db),
) -> EventTriggerSimulationResponse:
    trigger = await db.scalar(select(EventTrigger).where(
        EventTrigger.id == trigger_id, EventTrigger.org_id == current_user.org_id,
    ))
    if trigger is None:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")
    event = None
    if event_id is not None:
        if not has_permission(current_user.role, "event:read"):
            raise HTTPException(status_code=403, detail="Permission denied: event:read")
        event = await db.scalar(select(DeviceEvent).where(
            DeviceEvent.id == event_id, DeviceEvent.org_id == current_user.org_id,
        ))
        if event is None:
            raise HTTPException(status_code=404, detail="Событие не найдено")
        if event_type is not None and event_type != event.event_type:
            raise HTTPException(status_code=422, detail="Тип не совпадает с сохранённым событием")
        event_type = event.event_type
    if event_type is None:
        raise HTTPException(status_code=422, detail="Укажите event_type или event_id")
    response.headers["Cache-Control"] = "no-store"
    return await simulate_trigger(db, trigger, event_type, event)


@router.patch(
    "/{trigger_id}",
    response_model=EventTriggerResponse,
    summary="Обновить EventTrigger",
)
async def update_event_trigger(
    trigger_id: uuid.UUID,
    body: UpdateEventTriggerRequest,
    current_user: User = require_permission("pipeline:write"),
    db: AsyncSession = Depends(get_db),
) -> EventTriggerResponse:
    trigger = await db.scalar(select(EventTrigger).where(
        EventTrigger.id == trigger_id, EventTrigger.org_id == current_user.org_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not trigger:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")

    update_data = body.model_dump(exclude_unset=True)

    new_pipeline_id = body.pipeline_id
    if body.is_active is True or (new_pipeline_id is not None and new_pipeline_id != trigger.pipeline_id):
        await _require_active_pipeline(db, current_user.org_id, new_pipeline_id or trigger.pipeline_id)

    for key, value in update_data.items():
        if value is not None and hasattr(trigger, key):
            setattr(trigger, key, value)

    await db.commit()
    await db.refresh(trigger)

    logger.info(
        "event_trigger.updated",
        trigger_id=str(trigger.id),
        updated_fields=list(update_data.keys()),
    )
    return EventTriggerResponse.model_validate(trigger)


@router.delete(
    "/{trigger_id}",
    status_code=204,
    response_model=None,
    summary="Удалить EventTrigger (жёсткое удаление)",
)
async def delete_event_trigger(
    trigger_id: uuid.UUID,
    current_user: User = require_permission("pipeline:write"),
    db: AsyncSession = Depends(get_db),
) -> None:
    trigger = await db.get(EventTrigger, trigger_id)
    if not trigger or trigger.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")

    await db.delete(trigger)
    await db.commit()

    logger.info("event_trigger.deleted", trigger_id=str(trigger_id))


# ══════════════════════════════════════════════════════════════════════════════
#  Toggle
# ══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/{trigger_id}/toggle",
    response_model=EventTriggerResponse,
    summary="Включить / выключить EventTrigger",
)
async def toggle_event_trigger(
    trigger_id: uuid.UUID,
    active: bool = Query(..., description="true=включить, false=выключить"),
    current_user: User = require_permission("pipeline:write"),
    db: AsyncSession = Depends(get_db),
) -> EventTriggerResponse:
    """Переключить is_active у EventTrigger. Сохраняется в БД, переживает рестарт."""
    trigger = await db.scalar(select(EventTrigger).where(
        EventTrigger.id == trigger_id, EventTrigger.org_id == current_user.org_id,
    ).with_for_update().execution_options(populate_existing=True))
    if not trigger:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")

    if active:
        await _require_active_pipeline(db, current_user.org_id, trigger.pipeline_id)
    trigger.is_active = active
    await db.commit()
    await db.refresh(trigger)

    logger.info(
        "event_trigger.toggled",
        trigger_id=str(trigger_id),
        is_active=active,
    )
    return EventTriggerResponse.model_validate(trigger)
