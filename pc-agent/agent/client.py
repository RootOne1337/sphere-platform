"""
WS-клиент с exponential backoff, circuit breaker и сериализацией
исходящих сообщений через очередь (FIX 8.2 — websockets v12+ concurrent send).
"""
from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional

import websockets
from loguru import logger

from .config import config


class AgentWebSocketClient:
    def __init__(self, on_message: Callable) -> None:
        self.on_message = on_message
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._stop_event = asyncio.Event()

        # FIX 8.2: исходящая очередь — предотвращает ConcurrentMessageError
        # websockets v12+ запрещает concurrent await ws.send()
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)

        # FIX ARCH-5: сохраняем references на background tasks — защита от GC
        self._bg_tasks: set[asyncio.Task] = set()

        # FIX ARCH-6: circuit breaker
        self._consecutive_failures: int = 0
        self._CIRCUIT_THRESHOLD: int = 10
        self._circuit_open_until: float = 0.0
        self._CIRCUIT_COOLDOWN: float = 300.0  # 5 минут

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Основной цикл: подключение с exponential backoff и circuit breaker."""
        delay = config.reconnect_initial_delay

        while not self._stop_event.is_set():
            # FIX ARCH-6: circuit breaker check
            now = asyncio.get_event_loop().time()
            if now < self._circuit_open_until:
                wait = self._circuit_open_until - now
                logger.warning(f"Circuit OPEN, ждём {wait:.0f}с перед следующей попыткой")
                await asyncio.sleep(wait)
                self._consecutive_failures = 0

            try:
                await self._connect_once()
                # успешное подключение — сброс счётчика и задержки
                delay = config.reconnect_initial_delay
                self._consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._CIRCUIT_THRESHOLD:
                    self._circuit_open_until = (
                        asyncio.get_event_loop().time() + self._CIRCUIT_COOLDOWN
                    )
                    logger.error(
                        f"Circuit breaker OPEN после {self._consecutive_failures} ошибок подряд"
                    )
                logger.warning(
                    f"WS разорван: {exc!r}, reconnect через {delay:.1f}с "
                    f"(попытка #{self._consecutive_failures})"
                )
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()), timeout=delay
                    )
                    # stop_event сработал — выходим
                    break
                except asyncio.TimeoutError:
                    pass
                delay = min(delay * config.reconnect_backoff_factor, config.reconnect_max_delay)

    async def send(self, data: dict) -> None:
        """FIX 8.2: отправка через очередь, не напрямую в WebSocket."""
        if not self._connected:
            logger.debug("send() вызван при отключённом WS, сообщение пропущено")
            return
        try:
            self._send_queue.put_nowait(data)
        except asyncio.QueueFull:
            logger.warning("Очередь отправки переполнена — сообщение отброшено")

    async def stop(self) -> None:
        """Инициирует graceful shutdown."""
        self._stop_event.set()
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _connect_once(self) -> None:
        """Одна попытка подключения; живёт до разрыва соединения."""
        ws_url = (
            config.server_url.rstrip("/")
            + f"/ws/agent/{config.workstation_id}"
        )
        logger.info(f"Подключаемся к {ws_url}")

        async with websockets.connect(
            ws_url,
            ping_interval=20,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            self._ws = ws
            self._connected = True
            logger.info("WS-соединение установлено")

            # First-message auth — аналогично Android Agent
            await ws.send(json.dumps({
                "type": "auth",
                "token": config.agent_token,
                "workstation_id": config.workstation_id,
            }))
            logger.info("Auth-фрейм отправлен")

            # FIX 8.2: сериализующий цикл отправки
            send_task = asyncio.create_task(
                self._send_loop(ws), name="ws_send_loop"
            )
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.warning(f"Невалидный JSON: {raw[:200]!r}")
                        continue

                    # FIX ARCH-5: сохраняем task-reference, иначе GC может прибить
                    task = asyncio.create_task(
                        self.on_message(msg), name="dispatch"
                    )
                    self._bg_tasks.add(task)
                    task.add_done_callback(self._bg_tasks.discard)
            finally:
                self._connected = False
                self._ws = None
                send_task.cancel()
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass
                logger.info("WS-сессия завершена")

    async def _send_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        """
        FIX 8.2: последовательная отправка сообщений из очереди.
        websockets v12+ бросает ConcurrentMessageError при concurrent ws.send().
        """
        while True:
            data = await self._send_queue.get()
            try:
                await ws.send(json.dumps(data))
            except Exception as exc:
                logger.warning(f"Ошибка отправки WS-сообщения: {exc!r}")
                # соединение мертво — выходим, connect_once это поймает
                break
