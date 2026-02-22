# backend/api/ws/android/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-1. Android Agent WebSocket endpoint.
# ВАЖНО: Этот модуль — папка android/router.py (авто-дискавери main.py требует структуру пакета)
from __future__ import annotations

import json
import asyncio

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.models.device import Device
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.connection_manager import ConnectionManager, get_connection_manager

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


async def authenticate_ws_token(token: str, db: AsyncSession):
    """
    Проверить JWT токен из first-message WebSocket авторизации.
    Не использует OAuth2 Bearer в URL (безопасно от логирования).
    """
    import jwt as pyjwt
    from backend.core.security import decode_access_token
    from backend.models.user import User
    import uuid
    from fastapi import HTTPException

    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Проверить blacklist
    from backend.services.cache_service import CacheService
    cache = CacheService()
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def handle_agent_message(
    device_id: str,
    msg: dict,
    manager: ConnectionManager,
    status_cache: DeviceStatusCache,
) -> None:
    """Обработать входящее текстовое сообщение от Android агента."""
    msg_type = msg.get("type")
    if msg_type == "telemetry":
        await handle_telemetry(device_id, msg, status_cache)
    elif msg_type == "command_result":
        await handle_command_result(device_id, msg)
    elif msg_type == "event":
        await handle_device_event(device_id, msg)
    else:
        logger.debug("Unknown message type from android agent", device_id=device_id, type=msg_type)


async def handle_telemetry(
    device_id: str,
    msg: dict,
    status_cache: DeviceStatusCache,
) -> None:
    """Обновить статус устройства из телеметрии."""
    current = await status_cache.get_status(device_id)
    if current:
        if "battery" in msg:
            current.battery = msg["battery"]
        if "cpu" in msg:
            current.cpu_usage = msg["cpu"]
        if "ram_mb" in msg:
            current.ram_usage_mb = msg["ram_mb"]
        if "screen_on" in msg:
            current.screen_on = msg["screen_on"]
        if "vpn_active" in msg:
            current.vpn_active = msg["vpn_active"]
        await status_cache.set_status(device_id, current)


async def handle_command_result(device_id: str, msg: dict) -> None:
    """Опубликовать результат команды в Redis для ожидающего запроса."""
    command_id = msg.get("command_id") or msg.get("id")
    if not command_id:
        return
    try:
        from backend.database.redis_client import redis
        if redis:
            result_channel = f"sphere:agent:result:{device_id}:{command_id}"
            await redis.publish(result_channel, json.dumps(msg))
    except Exception as e:
        logger.warning("Failed to publish command result", device_id=device_id, error=str(e))


async def handle_device_event(device_id: str, msg: dict) -> None:
    """Перенаправить событие устройства в fleet events (SPLIT-5)."""
    try:
        from backend.websocket.event_publisher import get_event_publisher
        publisher = get_event_publisher()
        if publisher:
            from backend.schemas.events import FleetEvent, EventType
            await publisher.emit(FleetEvent(
                event_type=EventType.DEVICE_STATUS_CHANGE,
                device_id=device_id,
                org_id=msg.get("org_id", ""),
                payload=msg,
            ))
    except Exception as e:
        logger.debug("Fleet event publish skipped", device_id=device_id, error=str(e))


async def handle_agent_binary(
    device_id: str,
    data: bytes,
    manager: ConnectionManager,
) -> None:
    """Обработать бинарные данные (видеофрейм) от Android агента."""
    try:
        from backend.websocket.stream_bridge import get_stream_bridge
        bridge = get_stream_bridge()
        if bridge:
            await bridge.handle_agent_frame(device_id, data)
    except Exception as e:
        logger.debug("Stream bridge unavailable", device_id=device_id, error=str(e))


@router.websocket("/ws/android/{device_id}")
async def android_agent_ws(
    ws: WebSocket,
    device_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    await ws.accept()

    manager = get_connection_manager()

    # Redis для status cache
    redis = await get_redis()
    status_cache = DeviceStatusCache(redis)

    # Шаг 1: First-message auth (НЕ JWT в URL — чтобы не засветить в логах)
    try:
        first_msg = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return
    except Exception:
        await ws.close(code=4001, reason="receive_error")
        return

    token = first_msg.get("token")
    if not token:
        await ws.close(code=4001, reason="no_token")
        return

    # Валидация JWT
    from fastapi import HTTPException
    try:
        user = await authenticate_ws_token(token, db)
    except HTTPException:
        await ws.close(code=4001, reason="invalid_token")
        return

    # Проверить что device принадлежит организации
    import uuid
    try:
        device_uuid = uuid.UUID(device_id)
    except ValueError:
        await ws.close(code=4004, reason="invalid_device_id")
        return

    device = await db.get(Device, device_uuid)
    if not device or str(device.org_id) != str(user.org_id):
        await ws.close(code=4004, reason="device_not_found")
        return

    session_id = await manager.connect(ws, device_id, "android", str(user.org_id))
    await status_cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id,
        status="online",
        ws_session_id=session_id,
    ))

    # Запустить heartbeat (SPLIT-4)
    from backend.websocket.heartbeat import HeartbeatManager
    heartbeat = HeartbeatManager(ws, device_id, status_cache)
    await heartbeat.start()

    # Опубликовать device.online событие (SPLIT-5)
    try:
        from backend.websocket.event_publisher import get_event_publisher
        from backend.schemas.events import FleetEvent, EventType
        publisher = get_event_publisher()
        if publisher:
            await publisher.emit(FleetEvent(
                event_type=EventType.DEVICE_ONLINE,
                device_id=device_id,
                org_id=str(user.org_id),
                payload={"status": "online", "session_id": session_id},
            ))
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                match msg.get("type"):
                    case "pong":
                        await heartbeat.handle_pong(msg)
                    case "telemetry":
                        await handle_telemetry(device_id, msg, status_cache)
                    case "command_result":
                        await handle_command_result(device_id, msg)
                    case "event":
                        await handle_device_event(device_id, msg)
                    case _:
                        logger.debug(
                            "Unknown message type",
                            device_id=device_id,
                            type=msg.get("type"),
                        )
            elif "bytes" in data:
                await handle_agent_binary(device_id, data["bytes"], manager)
    except WebSocketDisconnect:
        pass
    finally:
        await heartbeat.stop()
        await manager.disconnect(device_id)
        await status_cache.mark_offline(device_id)

        # Опубликовать device.offline событие
        try:
            from backend.websocket.event_publisher import get_event_publisher
            from backend.schemas.events import FleetEvent, EventType
            publisher = get_event_publisher()
            if publisher:
                await publisher.emit(FleetEvent(
                    event_type=EventType.DEVICE_OFFLINE,
                    device_id=device_id,
                    org_id=str(user.org_id),
                    payload={"status": "offline"},
                ))
        except Exception:
            pass
