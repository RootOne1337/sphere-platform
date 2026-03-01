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
        # FIX-RECONNECT: трекинг delayed_stop задач для корректной отмены при быстром reconnect
        self._delayed_stop_tasks: dict[str, asyncio.Task] = {}
        # FIX-STOP: pending stop_stream для устройств, где агент был отключён в момент stop
        self._pending_stops: set[str] = set()
        # FIX-CACHE: Кэш последних SPS/PPS/IDR фреймов по device_id.
        # При reconnect viewer'а — немедленная отправка кэшированных фреймов.
        # Без этого viewer после реконнекта ждёт нового IDR от агента (может не дождаться).
        self._cached_sps: dict[str, bytes] = {}
        self._cached_pps: dict[str, bytes] = {}
        self._cached_idr: dict[str, bytes] = {}

    async def register_viewer(
        self,
        device_id: str,
        viewer_ws: WebSocket,
        session_id: str,
    ) -> None:
        """Зарегистрировать viewer для получения потока."""
        # FIX-RECONNECT: Отменить pending delayed_stop — viewer вернулся
        old_stop = self._delayed_stop_tasks.pop(device_id, None)
        if old_stop:
            old_stop.cancel()
            logger.debug("register_viewer: отменён delayed_stop", device_id=device_id)

        # FIX-STOP: viewer вернулся — убрать из pending stops
        self._pending_stops.discard(device_id)

        # FIX-RECONNECT: Если viewer уже зарегистрирован — очистить старую сессию
        old_task = self._viewer_tasks.pop(device_id, None)
        if old_task:
            old_task.cancel()
            logger.debug("register_viewer: отменён старый viewer_send_loop", device_id=device_id)
        self._queues.pop(device_id, None)

        self._queues[device_id] = VideoStreamQueue(device_id)
        self._viewer_sockets[device_id] = viewer_ws

        # FIX-CACHE: Немедленно отправить кэшированные SPS→PPS→IDR новому viewer'у.
        # Это позволяет декодеру сконфигурироваться и показать картинку без ожидания
        # нового IDR от агента (который может прийти через секунды или не прийти вовсе
        # из-за реконнектов Cloudflare tunnel).
        cached_frames_sent = 0
        for frame_key, label in [
            ("sps", "SPS"),
            ("pps", "PPS"),
            ("idr", "IDR"),
        ]:
            cached = getattr(self, f"_cached_{frame_key}").get(device_id)
            if cached:
                try:
                    await viewer_ws.send_bytes(cached)
                    cached_frames_sent += 1
                except Exception:
                    break
        if cached_frames_sent:
            logger.info(
                "register_viewer: отправлен кэш фреймов",
                device_id=device_id,
                cached_frames_sent=cached_frames_sent,
            )

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
                sent = await self.manager.send_to_device(device_id, {"type": "stop_stream"})
                if sent:
                    logger.info("Stream stopped (no reconnect in 2s)", device_id=device_id)
                    self._pending_stops.discard(device_id)
                else:
                    # FIX-STOP: агент не подключён — запомнить pending stop.
                    # При reconnect агента stop_stream будет доставлен.
                    self._pending_stops.add(device_id)
                    logger.warning(
                        "stop_stream не доставлен (агент offline) — добавлен в pending",
                        device_id=device_id,
                    )
            # Очистить себя из трекинга
            self._delayed_stop_tasks.pop(device_id, None)

        # FIX-RECONNECT: Отменить предыдущий delayed_stop если есть
        old_stop = self._delayed_stop_tasks.pop(device_id, None)
        if old_stop:
            old_stop.cancel()

        stop_task = asyncio.create_task(_delayed_stop())
        self._delayed_stop_tasks[device_id] = stop_task

    async def handle_agent_frame(self, device_id: str, frame_data: bytes) -> None:
        """
        Принять фрейм от агента. Кэширует SPS/PPS/IDR и кладёт в очередь.
        FIX-3.1: Прямая отправка блокировала цикл поллинга агента.
        FIX-CACHE: Кэширование ключевых NAL units для instant replay при reconnect viewer'а.
        """
        # FIX-CACHE: Определяем NAL type из payload (после 14-byte Sphere header).
        # Кэшируем SPS (7), PPS (8), IDR (5) — они нужны viewer'у для декодирования.
        if len(frame_data) > 18:
            payload = frame_data[14:]
            # Пропускаем Annex-B start code
            nal_byte_offset = 0
            if len(payload) >= 5 and payload[0:4] == b"\x00\x00\x00\x01":
                nal_byte_offset = 4
            elif len(payload) >= 4 and payload[0:3] == b"\x00\x00\x01":
                nal_byte_offset = 3
            if nal_byte_offset < len(payload):
                nal_type = payload[nal_byte_offset] & 0x1F
                if nal_type == 7:
                    self._cached_sps[device_id] = frame_data
                elif nal_type == 8:
                    self._cached_pps[device_id] = frame_data
                elif nal_type == 5:
                    self._cached_idr[device_id] = frame_data

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

    async def resume_stream_for_device(self, device_id: str) -> None:
        """FIX-RECONNECT: Вызывается при reconnect агента.

        Если viewer активен — повторно отправляет start_stream и viewer_connected,
        чтобы агент возобновил MediaProjection → H264Encoder → бинарные фреймы.
        Без этого при потере и восстановлении WS агента viewer получает 0 фреймов.
        """
        # FIX-STOP: Если есть pending stop — доставляем его вместо возобновления стрима
        if device_id in self._pending_stops:
            self._pending_stops.discard(device_id)
            await self.manager.send_to_device(device_id, {"type": "stop_stream"})
            logger.info("Pending stop_stream delivered on reconnect", device_id=device_id)
            return

        if device_id not in self._viewer_sockets:
            return

        await self.manager.send_to_device(device_id, {
            "type": "start_stream",
            "quality": "720p",
            "bitrate": 2_000_000,
        })
        await self.manager.send_to_device(device_id, {
            "type": "viewer_connected",
        })
        logger.info("Stream resumed for reconnected agent", device_id=device_id)

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
