# backend/api/ws/events/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-5. Fleet Events WebSocket для браузерного клиента.
# HIGH-4: выделен в подпакет events/router.py (не events.py)
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
from backend.schemas.events import FleetEvent

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


class FrontendConnection:
    def __init__(self, ws: WebSocket, org_id: str, filters: set[str]) -> None:
        self.ws = ws
        self.org_id = org_id
        self.filters = filters  # EventType фильтры, {} = все события


class EventsManager:
    """Менеджер WebSocket подключений браузерных клиентов.

    Подписывается на Redis PubSub каналы org:events для получения событий
    от ВСЕХ воркеров (multi-worker safe).
    """

    def __init__(self) -> None:
        self._clients: dict[str, list[FrontendConnection]] = {}  # org_id → list
        self._pubsub = None
        self._listen_task: asyncio.Task | None = None
        self._subscribed_orgs: set[str] = set()

    async def start(self, redis) -> None:
        """Запустить PubSub listener для browser event routing."""
        if redis is None:
            return
        self._redis = redis
        self._pubsub = redis.pubsub()
        self._listen_task = asyncio.create_task(self._listen_loop())
        logger.info("EventsManager PubSub listener started")

    async def stop(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.aclose()

    async def _subscribe_org(self, org_id: str) -> None:
        """Подписаться на канал org если ещё не подписаны."""
        if self._pubsub is None or org_id in self._subscribed_orgs:
            return
        from backend.websocket.channels import ChannelPattern
        channel = ChannelPattern.org_events(org_id)
        await self._pubsub.subscribe(channel)
        self._subscribed_orgs.add(org_id)

    async def _unsubscribe_org_if_empty(self, org_id: str) -> None:
        """Отписаться от канала org если нет клиентов."""
        if not self._clients.get(org_id) and org_id in self._subscribed_orgs:
            from backend.websocket.channels import ChannelPattern
            if self._pubsub:
                await self._pubsub.unsubscribe(ChannelPattern.org_events(org_id))
            self._subscribed_orgs.discard(org_id)

    async def _listen_loop(self) -> None:
        """Слушать Redis PubSub и рутить события в browser WS.
        Auto-restart при падении с exponential backoff."""
        if self._pubsub is None:
            return
        backoff = 1.0
        max_backoff = 30.0
        while True:
            try:
                # FIX: если нет подписок — ждём, иначе listen() вернётся немедленно
                # и while True образует CPU spinloop без единого await, блокируя event loop.
                if not self._pubsub.subscribed:
                    await asyncio.sleep(1.0)
                    continue

                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue
                    channel: str = message["channel"]
                    if not channel.startswith("sphere:org:events:"):
                        continue
                    org_id = channel.removeprefix("sphere:org:events:")
                    try:
                        data = json.loads(message["data"])
                        event = FleetEvent(**data)
                        await self._deliver_to_browsers(event)
                    except Exception as e:
                        logger.debug("EventsManager pubsub route error", error=str(e))
                    backoff = 1.0  # reset on successful iteration
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(
                    "EventsManager listen loop crashed — restarting",
                    error=str(e),
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                # Re-create pubsub connection
                try:
                    if self._pubsub:
                        await self._pubsub.aclose()
                    self._pubsub = self._redis.pubsub()
                    # Re-subscribe to org channels that still have clients
                    for org_id in list(self._subscribed_orgs):
                        from backend.websocket.channels import ChannelPattern
                        await self._pubsub.subscribe(ChannelPattern.org_events(org_id))
                    logger.info(
                        "EventsManager listen loop restarted",
                        subscribed_orgs=len(self._subscribed_orgs),
                    )
                except Exception as re_err:
                    logger.error("EventsManager reconnect failed", error=str(re_err))

    async def _deliver_to_browsers(self, event: FleetEvent) -> None:
        """Доставить событие локальным browser-клиентам (без Redis, in-process)."""
        clients = self._clients.get(event.org_id, [])
        if not clients:
            return

        payload = event.model_dump(mode="json")
        dead: list[FrontendConnection] = []

        for conn in clients:
            if conn.filters and event.event_type not in conn.filters:
                continue
            try:
                await conn.ws.send_json(payload)
            except Exception:
                dead.append(conn)

        for conn in dead:
            await self.remove_client(event.org_id, conn)

    async def add_client(self, org_id: str, conn: FrontendConnection) -> None:
        if org_id not in self._clients:
            self._clients[org_id] = []
        self._clients[org_id].append(conn)
        await self._subscribe_org(org_id)

    async def remove_client(self, org_id: str, conn: FrontendConnection) -> None:
        clients = self._clients.get(org_id, [])
        if conn in clients:
            clients.remove(conn)
        await self._unsubscribe_org_if_empty(org_id)

    async def publish_event(self, event: FleetEvent) -> None:
        """Разослать событие локальным browser-клиентам (вызывается EventPublisher для local delivery)."""
        await self._deliver_to_browsers(event)

    def client_count(self, org_id: str) -> int:
        return len(self._clients.get(org_id, []))


# Синглтон EventsManager
_events_manager: EventsManager | None = None


def get_events_manager() -> EventsManager:
    global _events_manager
    if _events_manager is None:
        _events_manager = EventsManager()
    return _events_manager


async def _startup_events_manager() -> None:
    """Запустить EventsManager PubSub listener при старте приложения."""
    from backend.database.redis_client import redis
    mgr = get_events_manager()
    await mgr.start(redis)


async def _shutdown_events_manager() -> None:
    """Остановить EventsManager PubSub listener."""
    mgr = get_events_manager()
    await mgr.stop()


from backend.core.lifespan_registry import register_shutdown, register_startup

register_startup("events_manager", _startup_events_manager)
register_shutdown("events_manager", _shutdown_events_manager)


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
    """Получить текущий снапшот fleet только для устройств данной организации."""
    try:
        from sqlalchemy import select

        from backend.database.engine import AsyncSessionLocal
        from backend.database.redis_client import redis_binary as _redis_bin
        from backend.models.device import Device
        from backend.services.device_status_cache import DeviceStatusCache

        if not _redis_bin:
            return {}
        cache = DeviceStatusCache(_redis_bin)

        # Получаем только device_ids, принадлежащие данной org (tenant-safe)
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Device.id).where(Device.org_id == org_id)
            )
            org_device_ids = [str(row[0]) for row in result.all()]

        if not org_device_ids:
            return {"total": 0, "online": 0, "devices": {}}

        statuses = await cache.bulk_get_status(org_device_ids)
        online = sum(1 for s in statuses.values() if s and s.status == "online")
        return {
            "total": len(org_device_ids),
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
) -> None:
    await ws.accept()

    events_manager = get_events_manager()

    # First-message auth
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        try:
            await ws.close(code=4003, reason="auth_timeout")
        except Exception:
            pass
        return
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close(code=4001, reason="receive_error")
        except Exception:
            pass
        return

    # Auth phase: DB session scoped to auth only — not held for WS lifetime
    org_id_str: str = ""
    filters: set[str] = set(first.get("filter", []))
    try:
        async with AsyncSessionLocal() as db:
            try:
                user = await authenticate_ws_token(first.get("token", ""), db)
            except HTTPException:
                await ws.close(code=4001, reason="invalid_token")
                return
            org_id_str = str(user.org_id)
    except HTTPException:
        raise
    except Exception:
        await ws.close(code=1011, reason="auth_error")
        return
    # DB session is now CLOSED — safe to enter long-lived WS loop

    conn = FrontendConnection(ws, org_id_str, filters)
    await events_manager.add_client(org_id_str, conn)

    # Отправить текущий снапшот fleet при подключении
    try:
        fleet_snap = await get_fleet_snapshot(org_id_str)
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
        await events_manager.remove_client(org_id_str, conn)
