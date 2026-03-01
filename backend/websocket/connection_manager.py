# backend/websocket/connection_manager.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-1. Потокобезопасный in-process реестр WebSocket соединений.
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

import structlog
from fastapi import WebSocket

logger = structlog.get_logger()


class ConnectionInfo:
    __slots__ = ("ws", "device_id", "agent_type", "org_id", "connected_at", "session_id")

    def __init__(
        self,
        ws: WebSocket,
        device_id: str,
        agent_type: str,
        org_id: str,
        session_id: str,
    ) -> None:
        self.ws = ws
        self.device_id = device_id
        self.agent_type = agent_type  # "android" | "pc"
        self.org_id = org_id
        self.connected_at = datetime.now(timezone.utc)
        self.session_id = session_id


class ConnectionManager:
    """
    Потокобезопасный реестр in-process.
    Для горизонтального масштабирования — используй Redis PubSub (SPLIT-2).
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # device_id → ConnectionInfo
        self._connections: dict[str, ConnectionInfo] = {}
        # org_id → set[device_id] (для broadcast по org)
        self._org_index: dict[str, set[str]] = {}

    async def connect(
        self,
        ws: WebSocket,
        device_id: str,
        agent_type: str,
        org_id: str,
    ) -> str:
        session_id = secrets.token_hex(16)
        async with self._lock:
            # Если устройство уже подключено — принудительно закрыть старое соединение
            if device_id in self._connections:
                old = self._connections[device_id]
                logger.info(
                    "Evicting old connection",
                    device_id=device_id,
                    old_session=old.session_id,
                )
                # FIX-CLOUDFLARE: Не блокируем на close() — через Cloudflare tunnel
                # await ws.close() может висеть 10+ секунд (TCP timeout). За это время
                # новый WS простаивает без данных и тоже дропается tunnel'ом.
                # Fire-and-forget с таймаутом 1 секунда — достаточно для graceful close.
                async def _evict_old(old_ws: WebSocket) -> None:
                    try:
                        await asyncio.wait_for(
                            old_ws.close(code=4001, reason="replaced_by_new_connection"),
                            timeout=1.0,
                        )
                    except Exception:
                        pass
                asyncio.create_task(_evict_old(old.ws))

            info = ConnectionInfo(ws, device_id, agent_type, org_id, session_id)
            self._connections[device_id] = info

            if org_id not in self._org_index:
                self._org_index[org_id] = set()
            self._org_index[org_id].add(device_id)

        logger.info(
            "Agent connected",
            device_id=device_id,
            agent_type=agent_type,
            session=session_id,
        )
        return session_id

    async def disconnect(self, device_id: str, session_id: str | None = None) -> ConnectionInfo | None:
        """Отключить агента. Если session_id передан — удалить ТОЛЬКО если текущая сессия совпадает.

        Это предотвращает race condition: старый handler вызывает disconnect() после того,
        как новая сессия уже зарегистрирована через connect(). Без проверки session_id
        старый handler удаляет НОВУЮ сессию из реестра → все send_to_device ломаются.
        """
        async with self._lock:
            current = self._connections.get(device_id)
            if current is None:
                return None
            # Если session_id передан и не совпадает — НЕ удаляем (новая сессия уже заменила старую)
            if session_id and current.session_id != session_id:
                logger.debug(
                    "disconnect: пропущено — сессия уже заменена",
                    device_id=device_id,
                    old_session=session_id,
                    current_session=current.session_id,
                )
                return None
            info = self._connections.pop(device_id)
            self._org_index.get(info.org_id, set()).discard(device_id)
        logger.info("Agent disconnected", device_id=device_id, session=info.session_id)
        return info

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """Отправить JSON сообщение конкретному агенту. Returns True если отправлено."""
        info = self._connections.get(device_id)
        if not info:
            msg_type = message.get("type", "unknown")
            logger.warning("send_to_device: устройство не подключено", device_id=device_id, msg_type=msg_type)
            return False
        try:
            await info.ws.send_json(message)
            msg_type = message.get("type", "unknown")
            # Логируем доставку stream-команд для диагностики
            if msg_type in ("start_stream", "stop_stream", "viewer_connected", "request_keyframe"):
                logger.info("send_to_device: доставлено", device_id=device_id, msg_type=msg_type)
            return True
        except Exception as e:
            logger.warning(
                "send_to_device failed",
                device_id=device_id,
                msg_type=message.get("type", "unknown"),
                error=str(e),
            )
            await self.disconnect(device_id, session_id=info.session_id)
            return False

    async def send_bytes_to_device(self, device_id: str, data: bytes) -> bool:
        """Отправить бинарные данные (видеофрейм и т.п.)"""
        info = self._connections.get(device_id)
        if not info:
            return False
        try:
            await info.ws.send_bytes(data)
            return True
        except Exception as e:
            logger.warning("Send bytes failed", device_id=device_id, error=str(e))
            await self.disconnect(device_id, session_id=info.session_id)
            return False

    async def broadcast_to_org(self, org_id: str, message: dict) -> int:
        """Broadcast JSON сообщение всем агентам организации. Returns кол-во отправленных."""
        device_ids = list(self._org_index.get(org_id, set()))
        if not device_ids:
            return 0
        tasks = [self.send_to_device(did, message) for did in device_ids]
        results = await asyncio.gather(*tasks)
        return sum(1 for r in results if r)

    def get_connected_devices(self, org_id: str) -> list[str]:
        return list(self._org_index.get(org_id, set()))

    def is_connected(self, device_id: str) -> bool:
        return device_id in self._connections

    @property
    def total_connections(self) -> int:
        return len(self._connections)


# Синглтон — один на процесс
_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager
