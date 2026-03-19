# backend/api/v1/event_triggers/router.py
# ВЛАДЕЛЕЦ: TZ-11+ Event Triggers REST API.
# CRUD + toggle для управления автоматическими реакциями на события.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.event_trigger import EventTrigger
from backend.models.pipeline import Pipeline
from backend.models.user import User
from backend.schemas.event_trigger import (
    CreateEventTriggerRequest,
    EventTriggerListResponse,
    EventTriggerResponse,
    UpdateEventTriggerRequest,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/event-triggers", tags=["event-triggers"])


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
            base.order_by(EventTrigger.created_at.desc())
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
    # Проверяем что pipeline существует и принадлежит той же организации
    pipeline = await db.get(Pipeline, body.pipeline_id)
    if not pipeline or pipeline.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="Pipeline не найден")

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
    trigger = await db.get(EventTrigger, trigger_id)
    if not trigger or trigger.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")

    update_data = body.model_dump(exclude_unset=True)

    # Если меняется pipeline_id — проверяем что новый pipeline существует
    if "pipeline_id" in update_data and update_data["pipeline_id"] is not None:
        pipeline = await db.get(Pipeline, update_data["pipeline_id"])
        if not pipeline or pipeline.org_id != current_user.org_id:
            raise HTTPException(status_code=404, detail="Pipeline не найден")

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
    trigger = await db.get(EventTrigger, trigger_id)
    if not trigger or trigger.org_id != current_user.org_id:
        raise HTTPException(status_code=404, detail="EventTrigger не найден")

    trigger.is_active = active
    await db.commit()
    await db.refresh(trigger)

    logger.info(
        "event_trigger.toggled",
        trigger_id=str(trigger_id),
        is_active=active,
    )
    return EventTriggerResponse.model_validate(trigger)
