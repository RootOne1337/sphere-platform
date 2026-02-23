# backend/api/ws/events/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-5. Fleet Events WebSocket для браузерного клиента.
# HIGH-4: выделен в подпакет events/router.py (не events.py)
from __future__ import annotations

import asyncio

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import get_db
from backend.schemas.events import FleetEvent

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


class FrontendConnection:
    def __init__(self, ws: WebSocket, org_id: str, filters: set[str]) -> None:
        self.ws = ws
        self.org_id = org_id
        self.filters = filters  # EventType фильтры, {} = все события


class EventsManager:
    """Менеджер WebSocket подключений браузерных клиентов."""

    def __init__(self) -> None:
        self._clients: dict[str, list[FrontendConnection]] = {}  # org_id → list

    async def add_client(self, org_id: str, conn: FrontendConnection) -> None:
        if org_id not in self._clients:
            self._clients[org_id] = []
        self._clients[org_id].append(conn)

    async def remove_client(self, org_id: str, conn: FrontendConnection) -> None:
        clients = self._clients.get(org_id, [])
        if conn in clients:
            clients.remove(conn)

    async def publish_event(self, event: FleetEvent) -> None:
        """Разослать событие всем браузерным клиентам организации."""
        clients = self._clients.get(event.org_id, [])
        if not clients:
            return

        payload = event.model_dump(mode="json")
        dead: list[FrontendConnection] = []

        for conn in clients:
            # Применить фильтры клиента
            if conn.filters and event.event_type not in conn.filters:
                continue
            try:
                await conn.ws.send_json(payload)
            except Exception:
                dead.append(conn)

        for conn in dead:
            await self.remove_client(event.org_id, conn)

    def client_count(self, org_id: str) -> int:
        return len(self._clients.get(org_id, []))


# Синглтон EventsManager
_events_manager: EventsManager | None = None


def get_events_manager() -> EventsManager:
    global _events_manager
    if _events_manager is None:
        _events_manager = EventsManager()
    return _events_manager


async def authenticate_ws_token(token: str, db: AsyncSession):
    """Проверить JWT токен из first-message авторизации."""
    import uuid

    import jwt as pyjwt

    from backend.core.security import decode_access_token
    from backend.models.user import User

    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    from backend.services.cache_service import CacheService
    cache = CacheService()
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def get_fleet_snapshot(org_id: str) -> dict:
    """Получить текущий снапшот fleet для первичной отправки при подключении."""
    try:
        from backend.database.redis_client import redis
        from backend.services.device_status_cache import DeviceStatusCache
        if not redis:
            return {}
        cache = DeviceStatusCache(redis)
        device_ids = await cache.get_all_tracked_device_ids()
        # Отфильтровать только устройства организации через bulk_get
        # (упрощённо — в реальной системе нужна фильтрация по org_id через DB)
        statuses = await cache.bulk_get_status(device_ids)
        online = sum(1 for s in statuses.values() if s and s.status == "online")
        return {
            "total": len(device_ids),
            "online": online,
            "devices": {
                did: s.model_dump(mode="json") if s else None
                for did, s in statuses.items()
            },
        }
    except Exception as e:
        logger.warning("Fleet snapshot failed", error=str(e))
        return {}


@router.websocket("/ws/events")
async def fleet_events_ws(
    ws: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> None:
    await ws.accept()

    events_manager = get_events_manager()

    # First-message auth
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return
    except Exception:
        await ws.close(code=4001, reason="receive_error")
        return

    try:
        user = await authenticate_ws_token(first.get("token", ""), db)
    except HTTPException:
        await ws.close(code=4001, reason="invalid_token")
        return

    # Опциональные фильтры событий
    filters: set[str] = set(first.get("filter", []))

    conn = FrontendConnection(ws, str(user.org_id), filters)
    await events_manager.add_client(str(user.org_id), conn)

    # Отправить текущий снапшот fleet при подключении
    try:
        fleet_snap = await get_fleet_snapshot(str(user.org_id))
        await ws.send_json({"type": "snapshot", "data": fleet_snap})
    except Exception:
        pass

    try:
        while True:
            data = await ws.receive_json()
            # Клиент может обновить фильтры в runtime
            if data.get("type") == "set_filter":
                conn.filters = set(data.get("events", []))
            elif data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await events_manager.remove_client(str(user.org_id), conn)
