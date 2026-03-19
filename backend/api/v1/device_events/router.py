# backend/api/v1/device_events/router.py
# ВЛАДЕЛЕЦ: TZ-11 Device Events — REST API для управления событиями устройств.
# AUTO-DISCOVERY: main.py автоматически подхватит этот роутер.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette import status as http_status

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.device_events import (
    CreateDeviceEventRequest,
    DeviceEventListResponse,
    DeviceEventResponse,
    EventStatsResponse,
)
from backend.services.device_event_service import DeviceEventService

router = APIRouter(prefix="/device-events", tags=["device-events"])


# ── DI фабрика ───────────────────────────────────────────────────────────
def get_device_event_service(
    db: AsyncSession = Depends(get_db),
) -> DeviceEventService:
    return DeviceEventService(db)


# ══════════════════════════════════════════════════════════════════════════
#  Endpoints
# ══════════════════════════════════════════════════════════════════════════


@router.get("/stats", response_model=EventStatsResponse)
async def get_event_stats(
    device_id: uuid.UUID | None = Query(None),
    current_user: User = require_permission("event:read"),
    svc: DeviceEventService = Depends(get_device_event_service),
) -> EventStatsResponse:
    """Агрегированная статистика событий."""
    return await svc.get_stats(
        org_id=current_user.org_id,
        device_id=device_id,
    )


@router.get("", response_model=DeviceEventListResponse)
async def list_device_events(
    device_id: uuid.UUID | None = Query(None),
    event_type: str | None = Query(None),
    severity: str | None = Query(None),
    account_id: uuid.UUID | None = Query(None),
    processed: bool | None = Query(None),
    search: str | None = Query(None),
    sort_by: str = Query("occurred_at"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=5000),
    current_user: User = require_permission("event:read"),
    svc: DeviceEventService = Depends(get_device_event_service),
    db: AsyncSession = Depends(get_db),
) -> DeviceEventListResponse:
    """Пагинированный список событий с фильтрами."""
    items, total = await svc.list_events(
        org_id=current_user.org_id,
        device_id=device_id,
        event_type=event_type,
        severity=severity,
        account_id=account_id,
        processed=processed,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    await db.commit()
    return DeviceEventListResponse(
        items=items, total=total, page=page, per_page=per_page, pages=pages,
    )


@router.post("", response_model=DeviceEventResponse, status_code=http_status.HTTP_201_CREATED)
async def create_device_event(
    body: CreateDeviceEventRequest,
    current_user: User = require_permission("event:write"),
    svc: DeviceEventService = Depends(get_device_event_service),
    db: AsyncSession = Depends(get_db),
) -> DeviceEventResponse:
    """Создать новое событие."""
    result = await svc.create_event(org_id=current_user.org_id, data=body)
    await db.commit()
    return result


@router.get("/{event_id}", response_model=DeviceEventResponse)
async def get_device_event(
    event_id: uuid.UUID,
    current_user: User = require_permission("event:read"),
    svc: DeviceEventService = Depends(get_device_event_service),
) -> DeviceEventResponse:
    """Получить событие по ID."""
    return await svc.get_event(event_id=event_id, org_id=current_user.org_id)


@router.post("/{event_id}/processed")
async def mark_event_processed(
    event_id: uuid.UUID,
    current_user: User = require_permission("event:write"),
    svc: DeviceEventService = Depends(get_device_event_service),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Пометить событие как обработанное."""
    await svc.mark_processed(event_id=event_id, org_id=current_user.org_id)
    await db.commit()
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)
