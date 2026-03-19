# backend/api/v1/devices/router.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-1. Device CRUD router.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.database.redis_client import get_redis_binary
from backend.models.user import User
from backend.schemas.device_register import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
)
from backend.schemas.device_status import (
    BulkStatusRequest,
    FleetStatusResponse,
    FleetSummaryResponse,
)
from backend.schemas.devices import (
    CreateDeviceRequest,
    DeviceListResponse,
    DeviceResponse,
    DeviceStatusResponse,
    UpdateDeviceRequest,
)
from backend.services.api_key_service import APIKeyService
from backend.services.cache_service import CacheService
from backend.services.device_registration_service import DeviceRegistrationService
from backend.services.device_service import DeviceService
from backend.services.device_status_cache import DeviceStatusCache

router = APIRouter(prefix="/devices", tags=["devices"])


def get_device_service(db: AsyncSession = Depends(get_db)) -> DeviceService:
    """
    DI-фабрика для DeviceService.
    FastAPI дедуплицирует Depends(get_db) — в одном запросе все зависимости
    получат одну и ту же сессию, что позволяет роутеру вызвать db.commit().
    """
    return DeviceService(db, CacheService())


async def get_status_cache(
    redis=Depends(get_redis_binary),
) -> DeviceStatusCache:
    return DeviceStatusCache(redis)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=DeviceResponse | None,
    summary="Информация об устройстве по X-API-Key (для агента)",
    tags=["devices"],
)
async def get_device_me(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> DeviceResponse | None:
    """
    Аутентификация по X-API-Key. Возвращает устройство или 404 если не найдено.
    Используется агентом при zero-touch enrollment для верификации ключа.
    """
    from fastapi import HTTPException
    if not x_api_key:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="X-API-Key required")
    from backend.services.api_key_service import APIKeyService
    api_key_svc = APIKeyService(db)
    key = await api_key_svc.authenticate(x_api_key)
    if not key:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    # Key is valid — try to find the device by X-Device-Id header
    if x_device_id:
        try:
            device_uuid = uuid.UUID(x_device_id)
            device = await svc.get_device(device_uuid, key.org_id)
            if device:
                return DeviceResponse.model_validate(device)
        except (ValueError, Exception):
            pass
    return None


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
    per_page: int = Query(50, ge=1, le=5000),
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
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
    # Обогащаем live-статус и телеметрию из Redis (один MGET на все устройства)
    if devices:
        device_ids = [str(d.id) for d in devices]
        live_statuses = await status_cache.bulk_get_status(device_ids)
        enriched = []
        for d in devices:
            live = live_statuses.get(str(d.id))
            if live:
                d.status = live.status
                d.battery_level = live.battery
                d.cpu_usage = live.cpu_usage
                d.ram_usage_mb = live.ram_usage_mb
                d.screen_on = live.screen_on
                d.adb_connected = live.adb_connected
                d.vpn_active = live.vpn_active
                d.last_heartbeat = live.last_heartbeat
            enriched.append(d)
        devices = enriched
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return DeviceListResponse(
        items=devices, total=total, page=page, per_page=per_page, pages=pages
    )


# ── Fleet status (bulk MGET) ──────────────────────────────────────────────────
# NOTE: These routes MUST appear before /{device_id} routes so FastAPI
# doesn't try to coerce "status" into a UUID.

@router.post(
    "/status/bulk",
    response_model=FleetStatusResponse,
    summary="Live статус для batch устройств (MGET — одна RTT до Redis)",
)
async def get_bulk_status(
    body: BulkStatusRequest,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> FleetStatusResponse:
    """Bulk live status для Dashboard. Возвращает только устройства этой org."""
    owned = await svc.filter_owned(body.device_ids, current_user.org_id)
    summary = await status_cache.get_fleet_summary(owned)
    return FleetStatusResponse(**summary)


@router.get(
    "/status/fleet",
    response_model=FleetSummaryResponse,
    summary="Сводный статус всего fleet организации",
)
async def get_fleet_status(
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> FleetSummaryResponse:
    """Total/online/busy/offline aggregation for Fleet Dashboard."""
    all_ids = await svc.get_all_device_ids(current_user.org_id)
    summary = await status_cache.get_fleet_summary(all_ids)
    return FleetSummaryResponse(
        total=summary["total"],
        online=summary["online"],
        busy=summary["busy"],
        offline=summary["offline"],
    )


# ── Auto-register (TZ-12 Agent Discovery) ────────────────────────────────────


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=201,
    summary="Автоматическая регистрация устройства (для агентов)",
    description=(
        "Автоматическая регистрация нового устройства. "
        "Аутентификация по enrollment API-ключу (X-API-Key с правом device:register). "
        "Идемпотентна: если fingerprint уже зарегистрирован — re-enrollment с новыми токенами."
    ),
)
async def register_device(
    body: DeviceRegisterRequest,
    x_api_key: str = Header(alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> DeviceRegisterResponse:
    """
    Автоматическая регистрация устройства при первом подключении.

    Требования к API-ключу:
    - Право 'device:register' в permissions
    - Активный, не истёкший

    Идемпотентность:
    - Повторный вызов с тем же fingerprint → возвращает существующее устройство + новые токены
    """
    from fastapi import HTTPException

    # Аутентификация API-ключа
    api_key_svc = APIKeyService(db)
    key = await api_key_svc.authenticate(x_api_key)
    if not key:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный или истёкший API-ключ",
        )

    # Проверка права device:register
    if "device:register" not in (key.permissions or []):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="API-ключ не имеет права device:register",
        )

    # Регистрация
    reg_svc = DeviceRegistrationService(db)
    result = await reg_svc.register_device(org_id=key.org_id, data=body)
    await db.commit()
    return result


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
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> DeviceResponse:
    device = await svc.get_device(device_id, current_user.org_id)
    live = await status_cache.get_status(str(device_id))
    if live:
        device.status = live.status
    return device


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
    response_model=None,
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
    response_model=None,
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


# ── Shell (TTY over HTTP) ─────────────────────────────────────────────────────


class ExecuteShellRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=4096)

@router.post(
    "/{device_id}/shell",
    summary="Выполнить команду shell на устройстве",
)
async def execute_shell(
    device_id: uuid.UUID,
    body: ExecuteShellRequest,
    current_user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    import asyncio
    import json
    import time

    from fastapi import HTTPException

    from backend.database.redis_client import get_redis_binary
    from backend.websocket.connection_manager import get_connection_manager

    device = await svc.get_device(device_id, current_user.org_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    manager = get_connection_manager()
    if not manager.is_connected(str(device_id)):
        raise HTTPException(status_code=400, detail="Device is offline")

    command_id = str(uuid.uuid4())
    send_ok = await manager.send_to_device(str(device_id), {
        "type": "SHELL",
        "command_id": command_id,
        "payload": {"cmd": body.command},
        "signed_at": int(time.time()),
        "ttl_seconds": 30,
    })
    if not send_ok:
        raise HTTPException(status_code=504, detail=f"Failed to send shell command to device {device_id}")

    redis = await get_redis_binary()
    if not redis:
        raise HTTPException(status_code=500, detail="Redis unavailable")

    pubsub = redis.pubsub()
    result_channel = f"sphere:agent:result:{device_id}:{command_id}"
    await pubsub.subscribe(result_channel)

    try:
        async def wait_for_result():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("status") == "completed":
                        return {"output": data.get("result", {}).get("output", "")}
                    elif data.get("status") == "failed":
                        return {"error": data.get("error", "Unknown error")}

        return await asyncio.wait_for(wait_for_result(), timeout=30.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Shell command timeout")
    finally:
        await pubsub.unsubscribe(result_channel)
        await pubsub.aclose()


# ── Logcat Viewer ─────────────────────────────────────────────────────────────

class RequestLogcatRequest(BaseModel):
    lines: int = Field(500, ge=1, le=10000)
    mode: str = "sphere"

@router.post(
    "/{device_id}/logcat",
    summary="Запросить logcat устройства",
)
async def request_logcat(
    device_id: uuid.UUID,
    body: RequestLogcatRequest,
    current_user: User = require_permission("device:read"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    import asyncio
    import json
    import time

    from fastapi import HTTPException

    from backend.database.redis_client import get_redis_binary
    from backend.websocket.connection_manager import get_connection_manager

    device = await svc.get_device(device_id, current_user.org_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    manager = get_connection_manager()
    if not manager.is_connected(str(device_id)):
        raise HTTPException(status_code=400, detail="Device is offline")

    command_id = str(uuid.uuid4())
    send_ok = await manager.send_to_device(str(device_id), {
        "type": "UPLOAD_LOGCAT",
        "command_id": command_id,
        "payload": {"lines": body.lines, "mode": body.mode},
        "signed_at": int(time.time()),
        "ttl_seconds": 15,
    })
    if not send_ok:
        raise HTTPException(status_code=504, detail=f"Failed to send logcat request to device {device_id}")

    redis = await get_redis_binary()
    if not redis:
        raise HTTPException(status_code=500, detail="Redis unavailable")

    pubsub = redis.pubsub()
    result_channel = f"sphere:agent:result:{device_id}:{command_id}"
    await pubsub.subscribe(result_channel)

    try:
        async def wait_for_result():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("status") == "completed":
                        return {"logcat": data.get("result", {}).get("logcat", "")}
                    elif data.get("status") == "failed":
                        return {"error": data.get("error", "Unknown error")}

        return await asyncio.wait_for(wait_for_result(), timeout=15.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Logcat request timeout")
    finally:
        await pubsub.unsubscribe(result_channel)
        await pubsub.aclose()


# ── Reboot ────────────────────────────────────────────────────────────────────

@router.post(
    "/{device_id}/reboot",
    summary="Перезагрузить устройство через агент",
)
async def reboot_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    import asyncio
    import json
    import time

    from fastapi import HTTPException

    from backend.database.redis_client import get_redis_binary
    from backend.websocket.connection_manager import get_connection_manager

    device = await svc.get_device(device_id, current_user.org_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    manager = get_connection_manager()
    if not manager.is_connected(str(device_id)):
        raise HTTPException(status_code=400, detail="Device is offline")

    command_id = str(uuid.uuid4())
    send_ok = await manager.send_to_device(str(device_id), {
        "type": "REBOOT",
        "command_id": command_id,
        "payload": {},
        "signed_at": int(time.time()),
        "ttl_seconds": 15,
    })
    if not send_ok:
        raise HTTPException(
            status_code=504,
            detail=f"Failed to send reboot command to device {device_id}",
        )

    redis = await get_redis_binary()
    if not redis:
        raise HTTPException(status_code=500, detail="Redis unavailable")

    pubsub = redis.pubsub()
    result_channel = f"sphere:agent:result:{device_id}:{command_id}"
    await pubsub.subscribe(result_channel)

    try:
        async def wait_for_result():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    if data.get("status") in ("completed", "received", "running"):
                        return {
                            "status": "reboot_initiated",
                            "device_id": str(device_id),
                        }
                    elif data.get("status") == "failed":
                        return {"error": data.get("error", "Reboot failed")}

        return await asyncio.wait_for(wait_for_result(), timeout=10.0)
    except asyncio.TimeoutError:
        # Устройство могло перезагрузиться до отправки ACK — это нормально
        return {
            "status": "reboot_initiated",
            "device_id": str(device_id),
            "note": "Device may have rebooted before acknowledging",
        }
    finally:
        await pubsub.unsubscribe(result_channel)
        await pubsub.aclose()
