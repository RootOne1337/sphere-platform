# backend/api/v1/devices/router.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-1. Device CRUD router.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.devices import (
    CreateDeviceRequest,
    DeviceListResponse,
    DeviceResponse,
    DeviceStatusResponse,
    UpdateDeviceRequest,
)
from backend.services.cache_service import CacheService
from backend.services.device_service import DeviceService

router = APIRouter(prefix="/devices", tags=["devices"])


def get_device_service(db: AsyncSession = Depends(get_db)) -> DeviceService:
    """
    DI-фабрика для DeviceService.
    FastAPI дедуплицирует Depends(get_db) — в одном запросе все зависимости
    получат одну и ту же сессию, что позволяет роутеру вызвать db.commit().
    """
    return DeviceService(db, CacheService())


# ── List ──────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=DeviceListResponse,
    summary="Список устройств с пагинацией и фильтрацией",
)
async def list_devices(
    status: str | None = None,
    group_id: uuid.UUID | None = None,
    type_filter: str | None = Query(None, alias="type"),
    search: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
) -> DeviceListResponse:
    devices, total = await svc.list_devices(
        org_id=current_user.org_id,
        status=status,
        group_id=group_id,
        type_filter=type_filter,
        search=search,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return DeviceListResponse(
        items=devices, total=total, page=page, per_page=per_page, pages=pages
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=DeviceResponse,
    status_code=201,
    summary="Создать устройство",
)
async def create_device(
    body: CreateDeviceRequest,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    result = await svc.create_device(current_user.org_id, body)
    await db.commit()
    return result


# ── Get one ───────────────────────────────────────────────────────────────────

@router.get(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Получить устройство по ID",
)
async def get_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
) -> DeviceResponse:
    return await svc.get_device(device_id, current_user.org_id)


# ── Update ────────────────────────────────────────────────────────────────────

@router.put(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Обновить устройство",
)
async def update_device(
    device_id: uuid.UUID,
    body: UpdateDeviceRequest,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    result = await svc.update_device(device_id, current_user.org_id, body)
    await db.commit()
    return result


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete(
    "/{device_id}",
    status_code=204,
    summary="Удалить устройство",
)
async def delete_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:delete"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.delete_device(device_id, current_user.org_id)
    await db.commit()


# ── Status (live Redis) ───────────────────────────────────────────────────────

@router.get(
    "/{device_id}/status",
    response_model=DeviceStatusResponse,
    summary="DB данные + live Redis статус устройства",
)
async def get_device_status(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
) -> DeviceStatusResponse:
    return await svc.get_device_with_live_status(device_id, current_user.org_id)


# ── ADB Connect ───────────────────────────────────────────────────────────────

@router.post(
    "/{device_id}/connect",
    status_code=204,
    summary="Инициировать ADB подключение через PC Agent (TZ-03 stub)",
)
async def connect_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.connect_adb(device_id, current_user.org_id)
    await db.commit()


# ── Screenshot ────────────────────────────────────────────────────────────────

@router.get(
    "/{device_id}/screenshot",
    summary="Запросить скриншот устройства (TZ-03 stub)",
)
async def take_screenshot(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    return await svc.request_screenshot(device_id, current_user.org_id)
