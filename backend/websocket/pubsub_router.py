# backend/websocket/pubsub_router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-2. Redis Pub/Sub Router — горизонтальное масштабирование WS.
from __future__ import annotations

import asyncio
import json
import secrets

import structlog
from fastapi import HTTPException

from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.websocket.channels import ChannelPattern
from backend.websocket.connection_manager import ConnectionManager, get_connection_manager

logger = structlog.get_logger()


class PubSubRouter:
    """
    Мост между Redis PubSub и локальным ConnectionManager.
    Один экземпляр на воркер, подписывается на нужные каналы.
    """

    def __init__(self, redis, connection_manager: ConnectionManager) -> None:
        self.redis = redis
        self.manager = connection_manager
        self._subscribed_channels: set[str] = set()
        self._pubsub = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Запустить прослушивание в фоне."""
        self._pubsub = self.redis.pubsub()
        self._task = asyncio.create_task(self._listen_loop())
        logger.info("PubSub router started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._pubsub:
            await self._pubsub.aclose()

    async def subscribe_device(self, device_id: str, org_id: str) -> None:
        """Подписаться на командный канал устройства при подключении агента."""
        if self._pubsub is None:
            return

        cmd_channel = ChannelPattern.agent_cmd(device_id)
        if cmd_channel not in self._subscribed_channels:
            await self._pubsub.subscribe(cmd_channel)
            self._subscribed_channels.add(cmd_channel)

        org_channel = ChannelPattern.org_events(org_id)
        if org_channel not in self._subscribed_channels:
            await self._pubsub.subscribe(org_channel)
            self._subscribed_channels.add(org_channel)

    async def unsubscribe_device(self, device_id: str) -> None:
        if self._pubsub is None:
            return
        cmd_channel = ChannelPattern.agent_cmd(device_id)
        if cmd_channel in self._subscribed_channels:
            await self._pubsub.unsubscribe(cmd_channel)
            self._subscribed_channels.discard(cmd_channel)

    async def _listen_loop(self) -> None:
        """Основной цикл прослушивания Redis."""
        if self._pubsub is None:
            return
        try:
            async for message in self._pubsub.listen():
                if message["type"] != "message":
                    continue

                channel: str = message["channel"]
                data = message["data"]

                try:
                    await self._route_message(channel, data)
                except Exception as e:
                    logger.error("PubSub route error", channel=channel, error=str(e))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("PubSub listen loop crashed", error=str(e))

    async def _route_message(self, channel: str, data: bytes | str) -> None:
        # MED-7: removeprefix() вместо split(":")[-1] — безопасно для device_id вида "192.168.1.1:5555"
        if channel.startswith("sphere:agent:cmd:"):
            device_id = channel.removeprefix("sphere:agent:cmd:")
            msg = json.loads(data) if isinstance(data, (bytes, str)) else data
            await self.manager.send_to_device(device_id, msg)

        elif channel.startswith("sphere:org:events:"):
            org_id = channel.removeprefix("sphere:org:events:")
            msg = json.loads(data) if isinstance(data, (bytes, str)) else data
            await self.manager.broadcast_to_org(org_id, msg)

        elif channel.startswith("sphere:stream:video:"):
            device_id = channel.removeprefix("sphere:stream:video:")
            raw = data if isinstance(data, bytes) else data.encode()
            await self._forward_video_to_viewers(device_id, raw)

    async def _forward_video_to_viewers(self, device_id: str, data: bytes) -> None:
        """Переслать видеопоток viewer WebSocket (SPLIT-3 StreamBridge)."""
        try:
            from backend.websocket.stream_bridge import get_stream_bridge
            bridge = get_stream_bridge()
            if bridge:
                await bridge.handle_agent_frame(device_id, data)
        except Exception as e:
            logger.debug("Video forward failed", device_id=device_id, error=str(e))


class PubSubPublisher:
    """
    Публикатор — отправляет команды через Redis PubSub.
    Используется API endpoint'ами для отправки команд агентам.
    """

    def __init__(self, redis) -> None:
        self.redis = redis

    async def send_command_to_device(
        self,
        device_id: str,
        command: dict,
    ) -> bool:
        """
        Отправить команду агенту через Redis PubSub.
        Команда будет доставлена воркеру, у которого есть подключение.
        Returns True если есть хотя бы один подписчик.
        """
        channel = ChannelPattern.agent_cmd(device_id)
        payload = json.dumps(command)
        subscribers = await self.redis.publish(channel, payload)
        return subscribers > 0

    async def broadcast_org_event(self, org_id: str, event: dict) -> int:
        channel = ChannelPattern.org_events(org_id)
        payload = json.dumps(event)
        return await self.redis.publish(channel, payload)

    async def send_command_wait_result(
        self,
        device_id: str,
        command: dict,
        timeout: float = 30.0,
    ) -> dict:
        """
        Отправить команду и ждать ответ.
        Использует временный канал sphere:agent:result:{device_id}:{command_id}.
        """
        command_id = command.setdefault("id", secrets.token_hex(8))
        result_channel = f"sphere:agent:result:{device_id}:{command_id}"

        # Подписаться ДО публикации во избежание race condition
        ps = self.redis.pubsub()
        await ps.subscribe(result_channel)

        try:
            sent = await self.send_command_to_device(device_id, command)
            if not sent:
                raise HTTPException(503, f"Device '{device_id}' is offline")

            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            async for msg in ps.listen():
                if msg["type"] == "message":
                    return json.loads(msg["data"])
                if loop.time() > deadline:
                    raise asyncio.TimeoutError()
        except asyncio.TimeoutError:
            raise HTTPException(504, f"Command timeout after {timeout}s")
        finally:
            await ps.unsubscribe(result_channel)
            await ps.aclose()

        raise HTTPException(504, "No response received")


# ── Singleton management ─────────────────────────────────────────────────────

_pubsub_router_instance: PubSubRouter | None = None
_pubsub_publisher_instance: PubSubPublisher | None = None


def get_pubsub_router() -> PubSubRouter | None:
    return _pubsub_router_instance


def get_pubsub_publisher() -> PubSubPublisher | None:
    return _pubsub_publisher_instance


async def _startup_pubsub() -> None:
    global _pubsub_router_instance, _pubsub_publisher_instance
    from backend.database.redis_client import redis
    if redis is None:
        logger.warning("Redis not available — PubSub router not started")
        return
    _pubsub_publisher_instance = PubSubPublisher(redis)
    _pubsub_router_instance = PubSubRouter(redis, get_connection_manager())
    await _pubsub_router_instance.start()


async def _shutdown_pubsub() -> None:
    global _pubsub_router_instance
    if _pubsub_router_instance:
        await _pubsub_router_instance.stop()
        _pubsub_router_instance = None


# Регистрируем хуки при импорте модуля (CRIT-3: не трогаем frozen main.py)
register_startup("pubsub_router", _startup_pubsub)
register_shutdown("pubsub_router", _shutdown_pubsub)
