# backend/api/v1/groups/router.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-2. Device Groups & Tags router.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.groups import (
    CreateGroupRequest,
    GroupResponse,
    MoveDevicesRequest,
    SetTagsRequest,
    UpdateGroupRequest,
)
from backend.services.group_service import GroupService

router = APIRouter(prefix="/groups", tags=["groups"])


def get_group_service(db: AsyncSession = Depends(get_db)) -> GroupService:
    return GroupService(db)


# ── List groups (with stats) ──────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[GroupResponse],
    summary="Список групп с количеством устройств online/total",
)
async def list_groups(
    current_user: User = require_permission("device:read"),
    svc: GroupService = Depends(get_group_service),
) -> list[GroupResponse]:
    return await svc.get_group_stats(current_user.org_id)


# ── Create group ──────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=GroupResponse,
    status_code=201,
    summary="Создать группу устройств",
)
async def create_group(
    body: CreateGroupRequest,
    current_user: User = require_permission("device:write"),
    svc: GroupService = Depends(get_group_service),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    result = await svc.create_group(current_user.org_id, body)
    await db.commit()
    return result


# ── Update group ──────────────────────────────────────────────────────────────

@router.put(
    "/{group_id}",
    response_model=GroupResponse,
    summary="Обновить группу устройств",
)
async def update_group(
    group_id: uuid.UUID,
    body: UpdateGroupRequest,
    current_user: User = require_permission("device:write"),
    svc: GroupService = Depends(get_group_service),
    db: AsyncSession = Depends(get_db),
) -> GroupResponse:
    result = await svc.update_group(group_id, current_user.org_id, body)
    await db.commit()
    return result


# ── Delete group ──────────────────────────────────────────────────────────────

@router.delete(
    "/{group_id}",
    status_code=204,
    summary="Удалить группу устройств",
)
async def delete_group(
    group_id: uuid.UUID,
    current_user: User = require_permission("device:delete"),
    svc: GroupService = Depends(get_group_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.delete_group(group_id, current_user.org_id)
    await db.commit()


# ── Move devices to group ─────────────────────────────────────────────────────

@router.post(
    "/{group_id}/devices/move",
    summary="Переместить устройства в группу",
)
async def move_devices(
    group_id: uuid.UUID,
    body: MoveDevicesRequest,
    current_user: User = require_permission("device:write"),
    svc: GroupService = Depends(get_group_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    moved = await svc.move_devices_to_group(
        body.device_ids, group_id, current_user.org_id
    )
    await db.commit()
    return {"moved": moved}


# ── Tags ──────────────────────────────────────────────────────────────────────

@router.get(
    "/tags",
    response_model=list[str],
    summary="Все теги в организации (для автодополнения)",
)
async def list_tags(
    current_user: User = require_permission("device:read"),
    svc: GroupService = Depends(get_group_service),
) -> list[str]:
    return await svc.list_all_tags(current_user.org_id)


@router.put(
    "/devices/{device_id}/tags",
    status_code=204,
    summary="Заменить теги устройства (идемпотентно)",
)
async def set_device_tags(
    device_id: str,
    body: SetTagsRequest,
    current_user: User = require_permission("device:write"),
    svc: GroupService = Depends(get_group_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.set_device_tags(device_id, body.tags, current_user.org_id)
    await db.commit()
