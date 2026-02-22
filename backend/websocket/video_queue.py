# backend/websocket/video_queue.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-3. Bounded video queue with drop strategy for backpressure.
from __future__ import annotations

import asyncio
import time
from collections import deque

import structlog

from backend.websocket.frames import VideoFrame

logger = structlog.get_logger()


class VideoStreamQueue:
    """
    Очередь с backpressure для видеопотока.

    Стратегия дропа при переполнении:
    1. Дроп устаревших P-frames сначала
    2. SEI metadata дропается первым
    3. I-frames (IDR/SPS/PPS) НИКОГДА не дропаются

    MERGE-1 (TZ-05): Это L2 server-side backpressure.
    FrameThrottle (TZ-05 SPLIT-4) = L1 agent-side throttle.
    Оба компонента сохраняются — двухуровневый pipeline.
    """

    MAX_SIZE = 50         # Макс фреймов в буфере
    MAX_LATENCY_MS = 200  # Дроп фреймов старше 200ms

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self._queue: deque[VideoFrame] = deque()
        self._lock = asyncio.Lock()

        # Метрики
        self.frames_queued = 0
        self.frames_dropped = 0
        self.frames_sent = 0

    async def put(self, frame: VideoFrame) -> bool:
        """
        Добавить фрейм. Returns True если добавлен, False если дропнут.
        """
        async with self._lock:
            # Сначала выбросить устаревшие фреймы
            self._evict_stale_sync()

            if len(self._queue) >= self.MAX_SIZE:
                # Очередь полная — нужно дропнуть что-то
                dropped = self._drop_one_droppable_sync()
                if not dropped and not frame.is_critical:
                    # Нет что дропать, дропаем входящий P-frame
                    self.frames_dropped += 1
                    logger.debug(
                        "Frame dropped (queue full)",
                        device_id=self.device_id,
                        nal_type=frame.nal_type,
                    )
                    return False

            self._queue.append(frame)
            self.frames_queued += 1
            return True

    async def get(self) -> VideoFrame | None:
        """Неблокирующее получение следующего фрейма."""
        async with self._lock:
            if not self._queue:
                return None
            frame = self._queue.popleft()
            self.frames_sent += 1
            return frame

    def _evict_stale_sync(self) -> None:
        """Удалить P-frames старше MAX_LATENCY_MS (вызывается под lock)."""
        now = time.monotonic()
        stale_count = 0
        fresh_queue: deque[VideoFrame] = deque()

        for frame in self._queue:
            age_ms = (now - frame.timestamp) * 1000
            if not frame.is_critical and age_ms > self.MAX_LATENCY_MS:
                self.frames_dropped += 1
                stale_count += 1
            else:
                fresh_queue.append(frame)

        if stale_count > 0:
            self._queue = fresh_queue
            logger.debug(
                "Evicted stale frames",
                device_id=self.device_id,
                count=stale_count,
            )

    def _drop_one_droppable_sync(self) -> bool:
        """Дропнуть один не-критичный фрейм из очереди (вызывается под lock)."""
        for i, frame in enumerate(self._queue):
            if not frame.is_critical:
                del self._queue[i]
                self.frames_dropped += 1
                return True
        return False

    @property
    def drop_ratio(self) -> float:
        total = self.frames_queued
        return self.frames_dropped / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._queue)
