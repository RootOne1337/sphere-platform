# backend/websocket/stream_bridge.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-3. StreamBridge: Android agent → browser viewer.
# FIX-3.1: Separate Task per viewer prevents slow viewer from blocking agent read loop.
from __future__ import annotations

import asyncio

import structlog
from fastapi import WebSocket

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.frames import VideoFrame
from backend.websocket.video_queue import VideoStreamQueue

logger = structlog.get_logger()


class VideoStreamBridge:
    """Мост от Android агента к viewer'у (браузер)."""

    def __init__(self, manager: ConnectionManager) -> None:
        self.manager = manager
        self._queues: dict[str, VideoStreamQueue] = {}
        self._viewer_sockets: dict[str, WebSocket] = {}
        self._viewer_tasks: dict[str, asyncio.Task] = {}

    async def register_viewer(
        self,
        device_id: str,
        viewer_ws: WebSocket,
        session_id: str,
    ) -> None:
        """Зарегистрировать viewer для получения потока."""
        self._queues[device_id] = VideoStreamQueue(device_id)
        self._viewer_sockets[device_id] = viewer_ws

        # FIX-3.1: Спавним отдельную Task для каждого viewer.
        # Эта Task в цикле читает из очереди и шлёт фреймы — медленный viewer
        # НЕ блокирует чтение от агента.
        task = asyncio.create_task(self._viewer_send_loop(device_id))
        self._viewer_tasks[device_id] = task

        # Запросить агента начать стриминг
        await self.manager.send_to_device(device_id, {
            "type": "start_stream",
            "quality": "720p",
            "bitrate": 2_000_000,
        })
        logger.info("Viewer registered", device_id=device_id, session_id=session_id)

    async def unregister_viewer(self, device_id: str) -> None:
        """Отменить viewer и остановить поток.

        stop_stream задержан на 2 секунды для обработки rapid reconnect (React StrictMode).
        В dev-режиме StrictMode делает cleanup+remount немедленно.
        Если viewer переподключается в течение 2s — stop_stream НЕ отправляется.
        """
        task = self._viewer_tasks.pop(device_id, None)
        if task:
            task.cancel()
        self._queues.pop(device_id, None)
        self._viewer_sockets.pop(device_id, None)
        logger.info("Viewer unregistered", device_id=device_id)

        # Debounce stop_stream: ждём 2s перед отправкой агенту
        async def _delayed_stop() -> None:
            await asyncio.sleep(2.0)
            # Если viewer переподключился — не останавливаем стрим
            if device_id not in self._viewer_sockets:
                await self.manager.send_to_device(device_id, {"type": "stop_stream"})
                logger.info("Stream stopped (no reconnect in 2s)", device_id=device_id)

        asyncio.create_task(_delayed_stop())

    async def handle_agent_frame(self, device_id: str, frame_data: bytes) -> None:
        """
        Принять фрейм от агента. ТОЛЬКО кладёт в очередь — НЕ шлёт напрямую!
        FIX-3.1: Прямая отправка блокировала цикл поллинга агента.
        """
        queue = self._queues.get(device_id)
        if not queue:
            return  # Нет viewer'а

        frame = VideoFrame(frame_data, device_id)
        await queue.put(frame)

    async def _viewer_send_loop(self, device_id: str) -> None:
        """
        FIX-3.1: Фоновая задача — читает из очереди и шлёт viewer'у.
        Полностью развязывает Producer (агент) и Consumer (браузер).
        """
        queue = self._queues.get(device_id)
        viewer_ws = self._viewer_sockets.get(device_id)
        if not queue or not viewer_ws:
            logger.warning("_viewer_send_loop: queue или viewer_ws не найдены", device_id=device_id)
            return

        frames_sent = 0
        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    # Пустая очередь — подождать немного, не грузить CPU
                    await asyncio.sleep(0.005)  # 5ms
                    continue
                try:
                    await viewer_ws.send_bytes(frame.data)
                    frames_sent += 1
                    if frames_sent == 1:
                        logger.info(
                            "viewer_send_loop: ПЕРВЫЙ фрейм отправлен viewer'у",
                            device_id=device_id,
                            size_bytes=len(frame.data),
                        )
                    elif frames_sent % 100 == 0:
                        logger.debug(
                            "viewer_send_loop: stats",
                            device_id=device_id,
                            frames_sent=frames_sent,
                            queue_size=queue.size,
                        )
                except Exception as e:
                    logger.warning(
                        "viewer_send_loop: ошибка отправки фрейма viewer'у",
                        device_id=device_id,
                        frames_sent=frames_sent,
                        error=str(e),
                    )
                    await self.unregister_viewer(device_id)
                    return
        except asyncio.CancelledError:
            logger.debug(
                "viewer_send_loop: cancelled",
                device_id=device_id,
                frames_sent=frames_sent,
            )
            pass  # Нормальное завершение при unregister

    def is_streaming(self, device_id: str) -> bool:
        return device_id in self._queues

    def get_drop_ratio(self, device_id: str) -> float:
        queue = self._queues.get(device_id)
        return queue.drop_ratio if queue else 0.0


# Синглтон
_stream_bridge: VideoStreamBridge | None = None


def get_stream_bridge() -> VideoStreamBridge | None:
    return _stream_bridge


def init_stream_bridge(manager: ConnectionManager) -> VideoStreamBridge:
    global _stream_bridge
    _stream_bridge = VideoStreamBridge(manager)
    return _stream_bridge
