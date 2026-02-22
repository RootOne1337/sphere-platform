# backend/api/v1/bulk/router.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-4. Bulk device operations router.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.bulk import (
    BulkActionRequest,
    BulkActionResponse,
    BulkDeleteRequest,
    BulkDeleteResponse,
)
from backend.services.bulk_service import BulkActionService
from backend.services.cache_service import CacheService
from backend.services.device_service import DeviceService
from backend.services.group_service import GroupService

router = APIRouter(prefix="/devices/bulk", tags=["devices", "bulk"])


def get_bulk_service(db: AsyncSession = Depends(get_db)) -> BulkActionService:
    cache = CacheService()
    device_svc = DeviceService(db, cache)
    group_svc = GroupService(db)
    return BulkActionService(db, device_svc, group_svc, cache)


def get_device_service_simple(db: AsyncSession = Depends(get_db)) -> DeviceService:
    return DeviceService(db, CacheService())


# ── Bulk action ───────────────────────────────────────────────────────────────

@router.post(
    "/action",
    response_model=BulkActionResponse,
    summary="Массовая операция над устройствами (max 500 за раз)",
)
async def bulk_action(
    body: BulkActionRequest,
    current_user: User = require_permission("device:write"),
    svc: BulkActionService = Depends(get_bulk_service),
    db: AsyncSession = Depends(get_db),
) -> BulkActionResponse:
    result = await svc.execute(body, current_user.org_id)
    await db.commit()
    return result


# ── Bulk delete ───────────────────────────────────────────────────────────────

@router.delete(
    "",
    response_model=BulkDeleteResponse,
    summary="Массовое удаление устройств (требует org_admin или выше)",
)
async def bulk_delete(
    body: BulkDeleteRequest,
    current_user: User = require_permission("device:delete"),
    svc: DeviceService = Depends(get_device_service_simple),
    db: AsyncSession = Depends(get_db),
) -> BulkDeleteResponse:
    deleted = await svc.bulk_soft_delete(body.device_ids, current_user.org_id)
    await db.commit()
    return BulkDeleteResponse(deleted=deleted)
