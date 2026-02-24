# backend/websocket/heartbeat.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-4. Heartbeat manager для WebSocket соединений агентов.
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from backend.services.device_status_cache import DeviceStatusCache

logger = structlog.get_logger()

# ─── MERGE-2: HEARTBEAT CONTRACT ────────────────────────────────────────────
# Эти константы — ЕДИНЫЙ ИСТОЧНИК ИСТИНЫ для таймаутов.
# TZ-07 Android Agent (SPLIT-2) ОБЯЗАН использовать ИДЕНТИЧНЫЕ значения:
#   HEARTBEAT_INTERVAL = 30с → Android: pong timeout = 30 + 15 = 45с
#   HEARTBEAT_TIMEOUT  = 15с → Server закрывает WS через 45с без pong
#
# При merge: проверить что Android SPLIT-2 содержит:
#   private val PONG_TIMEOUT_MS = 45_000L  // 30с interval + 15с timeout
# ─────────────────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL = 30.0   # Секунды между ping
HEARTBEAT_TIMEOUT = 15.0    # Секунды ожидания pong


class HeartbeatManager:
    """
    Высокоуровневый heartbeat поверх WebSocket ping/pong.

    Протокол:
    Server → Agent: {"type": "ping", "ts": 1234567890.123}
    Agent → Server: {"type": "pong", "ts": 1234567890.123, "battery": 87, ...}
    """

    def __init__(
        self,
        ws: WebSocket,
        device_id: str,
        status_cache: DeviceStatusCache,
    ) -> None:
        self.ws = ws
        self.device_id = device_id
        self.status_cache = status_cache
        self._last_pong: float = time.monotonic()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                # Проверить когда был последний pong
                since_pong = time.monotonic() - self._last_pong
                if since_pong > (HEARTBEAT_INTERVAL + HEARTBEAT_TIMEOUT):
                    logger.warning(
                        "Agent heartbeat timeout",
                        device_id=self.device_id,
                        since_pong_s=round(since_pong, 1),
                    )
                    try:
                        await self.ws.close(code=4008, reason="heartbeat_timeout")
                    except Exception:
                        pass  # WS уже закрыт — игнорируем double-close
                    return

                # Отправить ping
                ping_ts = time.time()
                await self.ws.send_json({
                    "type": "ping",
                    "ts": ping_ts,
                })
            except (WebSocketDisconnect, asyncio.CancelledError):
                return
            except Exception as e:
                logger.error(
                    "Heartbeat loop unexpected error",
                    device_id=self.device_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                return

    async def handle_pong(self, msg: dict) -> None:
        """Вызвать при получении pong от агента."""
        now = time.monotonic()
        self._last_pong = now

        # Логировать latency для мониторинга
        if "ts" in msg:
            server_latency_ms = round((time.time() - msg["ts"]) * 1000, 2)
            logger.debug(
                "Heartbeat pong received",
                device_id=self.device_id,
                latency_ms=server_latency_ms,
            )

        # Обновить live статус из телеметрии в pong
        status_update: dict = {}
        if "battery" in msg:
            status_update["battery"] = msg["battery"]
        if "cpu" in msg:
            status_update["cpu_usage"] = msg["cpu"]
        if "ram_mb" in msg:
            status_update["ram_usage_mb"] = msg["ram_mb"]
        if "screen_on" in msg:
            status_update["screen_on"] = msg["screen_on"]
        if "vpn_active" in msg:
            status_update["vpn_active"] = msg["vpn_active"]

        # Всегда обновляем last_heartbeat при получении pong
        current = await self.status_cache.get_status(self.device_id)
        if current:
            for key, val in status_update.items():
                setattr(current, key, val)
            current.last_heartbeat = datetime.now(timezone.utc)
            await self.status_cache.set_status(self.device_id, current)

        # TZ-05 SPLIT-4: обновить Prometheus stream-метрики из pong телеметрии
        stream_data = msg.get("stream")
        if stream_data and isinstance(stream_data, dict):
            try:
                from backend.websocket.stream_metrics import StreamMetrics
                StreamMetrics(self.device_id).update_from_pong(stream_data)
            except Exception as e:
                logger.debug("stream_metrics update failed", error=str(e))
