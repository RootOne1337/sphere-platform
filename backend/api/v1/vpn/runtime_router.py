from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.database.redis_client import get_redis_binary
from backend.models.device import Device, device_group_members
from backend.schemas.vpn.runtime import AppVpnDevice, AppVpnDevicePage
from backend.services.device_status_cache import DeviceStatusCache

router = APIRouter(prefix="/runtime")


@router.get("", response_model=AppVpnDevicePage)
async def app_vpn_devices(
    page: int = Query(1, ge=1, le=10000), page_size: int = Query(25, ge=1, le=100),
    search: str = Query("", max_length=120), group_id: uuid.UUID | None = None,
    user=require_permission("vpn:read"), db: AsyncSession = Depends(get_db), redis=Depends(get_redis_binary),
):
    # Database ownership precedes cache reads. Never expose cross-tenant Redis
    # records by accepting an arbitrary list of device IDs from the caller.
    filters = [Device.org_id == user.org_id, Device.is_active.is_(True)]
    if search.strip():
        escaped = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        filters.append(Device.name.ilike(f"%{escaped}%", escape="\\"))
    if group_id:
        filters.append(Device.id.in_(select(device_group_members.c.device_id).where(device_group_members.c.group_id == group_id)))
    total = await db.scalar(select(func.count()).select_from(Device).where(*filters))
    devices = (await db.scalars(select(Device).where(*filters).order_by(Device.name, Device.id)
                               .offset((page - 1) * page_size).limit(page_size))).all()
    now = datetime.now(timezone.utc)
    live = await DeviceStatusCache(redis).bulk_get_status([str(d.id) for d in devices], as_of=now)
    items = []
    for device in devices:
        status = live.get(str(device.id))
        observed = status.app_vpn if status else None
        online = bool(status and status.status in ("online", "busy") and status.last_heartbeat
                      and status.last_heartbeat.tzinfo and 0 <= (now - status.last_heartbeat).total_seconds() < 120)
        items.append(AppVpnDevice(
            device_id=str(device.id), name=device.name, model=device.model, android_version=device.android_version,
            status=status.status if status and (online or status.status in ("connecting", "error")) else "offline", agent_version=status.agent_version if status else None,
            last_heartbeat=status.last_heartbeat if status else None, observation=observed,
            freshness=observed.freshness(status.ws_session_id, online, now) if observed else "unknown",
        ))
    return AppVpnDevicePage(items=items, total=total or 0, page=page, page_size=page_size, as_of=now)
