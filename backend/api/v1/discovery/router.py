# backend/api/v1/discovery/router.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-5. Network discovery router.
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.models.user import User
from backend.schemas.discovery import DiscoverRequest, DiscoverResponse
from backend.services.cache_service import CacheService
from backend.services.device_service import DeviceService
from backend.services.discovery_service import DiscoveryService

router = APIRouter(prefix="/discovery", tags=["discovery"])


def get_discovery_service(db: AsyncSession = Depends(get_db)) -> DiscoveryService:
    device_svc = DeviceService(db, CacheService())
    return DiscoveryService(db, device_svc)


@router.post(
    "/scan",
    response_model=DiscoverResponse,
    summary="Сканировать подсеть через PC Agent для обнаружения ADB-устройств",
)
async def scan_subnet(
    body: DiscoverRequest,
    current_user: User = require_permission("device:write"),
    svc: DiscoveryService = Depends(get_discovery_service),
    db: AsyncSession = Depends(get_db),
) -> DiscoverResponse:
    """
    Сканирование /24 (256 хостов × 2 порта) ≤ 15 секунд.
    Subnet > /16 отклоняется с 422.
    Найденные устройства авторегистрируются если auto_register=True.
    """
    result = await svc.discover_subnet(body, current_user.org_id)
    if result.registered > 0:
        await db.commit()
    return result
