# -*- coding: utf-8 -*-
"""
WebSocket-клиент для нагрузочного тестирования.

Обёртка над библиотекой ``websockets`` с метриками, автоматическим
reconnect и поддержкой бинарных фреймов.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine

import websockets
from websockets.asyncio.client import ClientConnection

from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.ws")

# Таймаут первого сообщения аутентификации (серверный порог — 30 с)
_AUTH_TIMEOUT = 25.0
_CONNECT_TIMEOUT = 15.0


class WsClient:
    """Асинхронный WebSocket-клиент с метриками.

    Параметры:
        ws_url: Базовый WS URL (ws://host:port).
        device_id: Идентификатор устройства для URL path.
        token: JWT или API-ключ для аутентификации.
        metrics: Сборщик метрик.
    """

    def __init__(
        self,
        ws_url: str,
        device_id: str,
        token: str,
        metrics: MetricsCollector,
    ) -> None:
        self._ws_url = ws_url.rstrip("/")
        self._device_id = device_id
        self._token = token
        self._metrics = metrics
        self._conn: ClientConnection | None = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._conn is not None

    @property
    def full_url(self) -> str:
        return f"{self._ws_url}/ws/android/{self._device_id}"

    # ---------------------------------------------------------------
    # Подключение
    # ---------------------------------------------------------------

    async def connect(self) -> bool:
        """Подключиться и отправить first-message auth.

        Returns:
            True — аутентификация успешна.
        """
        t0 = time.monotonic()
        try:
            self._conn = await asyncio.wait_for(
                websockets.connect(
                    self.full_url,
                    max_size=2**22,  # 4 MiB
                    ping_interval=None,  # Мы сами управляем heartbeat
                    ping_timeout=None,
                    close_timeout=5,
                ),
                timeout=_CONNECT_TIMEOUT,
            )

            connect_ms = (time.monotonic() - t0) * 1000
            self._metrics.record("ws_connect_latency", connect_ms)
            self._metrics.inc("ws_connect_total")

            # First-message auth
            auth_msg = json.dumps({"token": self._token})
            await self._conn.send(auth_msg)

            # Ждём ответ от сервера (обычно noop или ping)
            try:
                await asyncio.wait_for(
                    self._conn.recv(), timeout=_AUTH_TIMEOUT
                )
                auth_ms = (time.monotonic() - t0) * 1000
                self._metrics.record("ws_auth_latency", auth_ms)
            except asyncio.TimeoutError:
                self._metrics.inc("ws_auth_timeout")
                await self._close_silent()
                return False

            self._connected = True
            self._metrics.inc("ws_auth_success")
            return True

        except (
            OSError,
            asyncio.TimeoutError,
            websockets.exceptions.WebSocketException,
        ) as exc:
            connect_ms = (time.monotonic() - t0) * 1000
            self._metrics.record("ws_connect_latency", connect_ms)
            self._metrics.inc("ws_connect_error")
            logger.debug("WS connect error [%s]: %s", self._device_id, exc)
            return False

    # ---------------------------------------------------------------
    # Отправка / Получение
    # ---------------------------------------------------------------

    async def send_text(self, message: str) -> bool:
        """Отправить текстовый фрейм."""
        if not self.is_connected or self._conn is None:
            return False
        try:
            await self._conn.send(message)
            self._metrics.inc("ws_frames_sent")
            return True
        except websockets.exceptions.WebSocketException:
            self._connected = False
            self._metrics.inc("ws_send_error")
            return False

    async def send_binary(self, data: bytes) -> bool:
        """Отправить бинарный фрейм (например, H.264)."""
        if not self.is_connected or self._conn is None:
            return False
        try:
            await self._conn.send(data)
            self._metrics.inc("ws_binary_frames_sent")
            return True
        except websockets.exceptions.WebSocketException:
            self._connected = False
            self._metrics.inc("ws_send_error")
            return False

    async def recv(self, timeout: float = 60.0) -> str | bytes | None:
        """Получить одно сообщение.

        Returns:
            Текст / байты или None при ошибке / таймауте.
        """
        if not self.is_connected or self._conn is None:
            return None
        try:
            msg = await asyncio.wait_for(self._conn.recv(), timeout=timeout)
            self._metrics.inc("ws_frames_received")
            return msg
        except asyncio.TimeoutError:
            return None
        except websockets.exceptions.WebSocketException:
            self._connected = False
            self._metrics.inc("ws_recv_error")
            return None

    async def recv_json(self, timeout: float = 60.0) -> dict[str, Any] | None:
        """Получить JSON-сообщение."""
        raw = await self.recv(timeout)
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    # ---------------------------------------------------------------
    # Итератор сообщений
    # ---------------------------------------------------------------

    async def listen(
        self,
        handler: Callable[[str | bytes], Coroutine[Any, Any, None]],
        stop_event: asyncio.Event | None = None,
    ) -> None:
        """Слушать сообщения и вызывать handler для каждого.

        Завершается при закрытии соединения или установке stop_event.
        """
        if not self.is_connected or self._conn is None:
            return

        try:
            async for message in self._conn:
                self._metrics.inc("ws_frames_received")
                await handler(message)
                if stop_event and stop_event.is_set():
                    break
        except websockets.exceptions.ConnectionClosed as exc:
            self._connected = False
            self._metrics.inc("ws_disconnect")
            logger.debug(
                "WS closed [%s]: code=%s reason=%s",
                self._device_id, exc.code, exc.reason,
            )

    # ---------------------------------------------------------------
    # Закрытие
    # ---------------------------------------------------------------

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Graceful закрытие соединения."""
        self._connected = False
        if self._conn is not None:
            try:
                await self._conn.close(code, reason)
            except Exception:
                pass
            self._conn = None

    async def _close_silent(self) -> None:
        """Закрытие без логирования."""
        self._connected = False
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    @property
    def close_code(self) -> int | None:
        """Код закрытия соединения (если закрыто)."""
        if self._conn is not None:
            cc = self._conn.close_code
            return cc
        return None
