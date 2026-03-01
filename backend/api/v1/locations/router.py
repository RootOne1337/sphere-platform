# backend/api/v1/locations/router.py
# ВЛАДЕЛЕЦ: TZ-02. Location CRUD + назначение устройств.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.locations import (
    CreateLocationRequest,
    LocationResponse,
    MoveDevicesToLocationRequest,
    UpdateLocationRequest,
)
from backend.services.location_service import LocationService

router = APIRouter(prefix="/locations", tags=["locations"])


def get_location_service(db: AsyncSession = Depends(get_db)) -> LocationService:
    return LocationService(db)


# ── List (со статистикой) ─────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[LocationResponse],
    summary="Список локаций с количеством устройств online/total",
)
async def list_locations(
    current_user: User = require_permission("device:read"),
    svc: LocationService = Depends(get_location_service),
) -> list[LocationResponse]:
    return await svc.get_location_stats(current_user.org_id)


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=LocationResponse,
    status_code=201,
    summary="Создать локацию",
)
async def create_location(
    body: CreateLocationRequest,
    current_user: User = require_permission("device:write"),
    svc: LocationService = Depends(get_location_service),
    db: AsyncSession = Depends(get_db),
) -> LocationResponse:
    result = await svc.create_location(current_user.org_id, body)
    await db.commit()
    return result


# ── Update ────────────────────────────────────────────────────────────────────

@router.put(
    "/{location_id}",
    response_model=LocationResponse,
    summary="Обновить локацию",
)
async def update_location(
    location_id: uuid.UUID,
    body: UpdateLocationRequest,
    current_user: User = require_permission("device:write"),
    svc: LocationService = Depends(get_location_service),
    db: AsyncSession = Depends(get_db),
) -> LocationResponse:
    result = await svc.update_location(location_id, current_user.org_id, body)
    await db.commit()
    return result


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete(
    "/{location_id}",
    status_code=204,
    response_model=None,
    summary="Удалить локацию",
)
async def delete_location(
    location_id: uuid.UUID,
    current_user: User = require_permission("device:delete"),
    svc: LocationService = Depends(get_location_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.delete_location(location_id, current_user.org_id)
    await db.commit()


# ── Назначить устройства в локацию ────────────────────────────────────────────

@router.post(
    "/{location_id}/devices",
    summary="Назначить устройства в локацию (аддитивно)",
)
async def assign_devices(
    location_id: uuid.UUID,
    body: MoveDevicesToLocationRequest,
    current_user: User = require_permission("device:write"),
    svc: LocationService = Depends(get_location_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    added = await svc.assign_devices_to_location(
        body.device_ids, location_id, current_user.org_id
    )
    await db.commit()
    return {"assigned": added}


# ── Убрать устройства из локации ──────────────────────────────────────────────

@router.delete(
    "/{location_id}/devices",
    summary="Убрать устройства из локации",
)
async def remove_devices(
    location_id: uuid.UUID,
    body: MoveDevicesToLocationRequest,
    current_user: User = require_permission("device:write"),
    svc: LocationService = Depends(get_location_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    removed = await svc.remove_devices_from_location(
        body.device_ids, location_id, current_user.org_id
    )
    await db.commit()
    return {"removed": removed}
