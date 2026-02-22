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
                try:
                    await old.ws.close(code=4001, reason="replaced_by_new_connection")
                except Exception:
                    pass

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

    async def disconnect(self, device_id: str) -> ConnectionInfo | None:
        async with self._lock:
            info = self._connections.pop(device_id, None)
            if info:
                self._org_index.get(info.org_id, set()).discard(device_id)
        if info:
            logger.info("Agent disconnected", device_id=device_id, session=info.session_id)
        return info

    async def send_to_device(self, device_id: str, message: dict) -> bool:
        """Отправить JSON сообщение конкретному агенту. Returns True если отправлено."""
        info = self._connections.get(device_id)
        if not info:
            return False
        try:
            await info.ws.send_json(message)
            return True
        except Exception as e:
            logger.warning("Send failed", device_id=device_id, error=str(e))
            await self.disconnect(device_id)
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
            await self.disconnect(device_id)
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
