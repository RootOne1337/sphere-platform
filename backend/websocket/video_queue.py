# backend/websocket/video_queue.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-3. Bounded video queue with drop strategy for backpressure.
from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable

import structlog

from backend.websocket.frames import VideoFrame
from backend.websocket.stream_observability import record_server_queue_drop

logger = structlog.get_logger()


class VideoStreamQueue:
    """
    Очередь с backpressure для видеопотока.

    On a picture gap, discard the dependent chain and wait for a fresh IDR.
    Configuration packets may pass during recovery. Never send later P-frames
    after evicting a reference picture, even when those P-frames are fresh.

    MERGE-1 (TZ-05): Это L2 server-side backpressure.
    FrameThrottle (TZ-05 SPLIT-4) = L1 agent-side throttle.
    Оба компонента сохраняются — двухуровневый pipeline.
    """

    MAX_SIZE = 50         # Макс фреймов в буфере
    MAX_LATENCY_MS = 200  # Дроп фреймов старше 200ms
    MAX_BYTES = 8 * 1024 * 1024

    def __init__(self, device_id: str, queue_stage: str = "viewer",
                 on_recovery: Callable[[], None] | None = None) -> None:
        if queue_stage not in {"viewer", "agent_to_redis"}:
            raise ValueError("unsupported stream queue stage")
        self.device_id = device_id
        self.queue_stage = queue_stage
        self._queue: deque[VideoFrame] = deque()
        self._lock = asyncio.Lock()
        self._ready = asyncio.Event()
        self._bytes = 0
        self._awaiting_idr = False
        self._on_recovery = on_recovery
        self._last_recovery_request: float | None = None
        self.frames_received = 0

        # Метрики
        self.frames_queued = 0
        self.frames_dropped = 0
        self.frames_sent = 0

    async def put(self, frame: VideoFrame) -> bool:
        """
        Добавить фрейм. Returns True если добавлен, False если дропнут.
        """
        async with self._lock:
            self.frames_received += 1
            if len(frame.data) > self.MAX_BYTES:
                self._record_drop("oversize")
                if frame.is_picture or frame.is_configuration:
                    self._invalidate_chain_sync("reference_gap")
                return False
            # Сначала выбросить устаревшие фреймы
            self._evict_stale_sync()

            if len(self._queue) >= self.MAX_SIZE or self._bytes + len(frame.data) > self.MAX_BYTES:
                self._invalidate_chain_sync("backpressure")
                # Configuration-only floods must also obey both hard bounds.
                while self._queue and (len(self._queue) >= self.MAX_SIZE or
                                       self._bytes + len(frame.data) > self.MAX_BYTES):
                    self._bytes -= len(self._queue.popleft().data)
                    self._record_drop("critical_eviction")

            if self._awaiting_idr and frame.is_picture and not frame.is_keyframe:
                self._record_drop("awaiting_idr")
                self._request_recovery_sync()
                return False

            if frame.is_keyframe:
                self._awaiting_idr = False
                self._last_recovery_request = None

            self._queue.append(frame)
            self._bytes += len(frame.data)
            self._ready.set()
            self.frames_queued += 1
            return True

    async def get(self) -> VideoFrame | None:
        """Неблокирующее получение следующего фрейма."""
        async with self._lock:
            # The writer can stall while no new packet arrives. Enforce the
            # deadline at dequeue too, including old IDRs, not just on put().
            self._evict_stale_sync()
            if not self._queue:
                return None
            frame = self._queue.popleft()
            self._bytes -= len(frame.data)
            if not self._queue:
                self._ready.clear()
            self.frames_sent += 1
            return frame

    async def wait(self) -> VideoFrame:
        """Sleep until a frame is available instead of polling every 5 ms."""
        while True:
            await self._ready.wait()
            frame = await self.get()
            if frame is not None:
                return frame

    async def invalidate(self) -> None:
        """Publication outcome was uncertain: fence the remaining references."""
        async with self._lock:
            self._invalidate_chain_sync("reference_gap")

    def _evict_stale_sync(self) -> None:
        """Expire pictures and their dependants; keep codec configuration."""
        now = time.monotonic()
        if any(frame.is_picture and (now - frame.timestamp) * 1000 > self.MAX_LATENCY_MS
               for frame in self._queue):
            self._invalidate_chain_sync("stale")

    def _invalidate_chain_sync(self, reason: str) -> None:
        kept: deque[VideoFrame] = deque()
        for frame in self._queue:
            if frame.is_configuration:
                kept.append(frame)
            else:
                self._bytes -= len(frame.data)
                self._record_drop(reason)
        self._queue = kept
        if not kept:
            self._ready.clear()
        self._awaiting_idr = True
        self._request_recovery_sync()

    def _request_recovery_sync(self) -> None:
        now = time.monotonic()
        if self._last_recovery_request is not None and now - self._last_recovery_request < 1:
            return
        self._last_recovery_request = now
        if self._on_recovery:
            try:
                # This callback only schedules control; never waits for I/O
                # inside a queue lock or the shared Redis subscription reader.
                self._on_recovery()
            except Exception:
                logger.debug("stream_queue_recovery_schedule_failed", device_id=self.device_id)

    def _record_drop(self, reason: str) -> None:
        self.frames_dropped += 1
        record_server_queue_drop(self.device_id, self.queue_stage, reason)

    @property
    def drop_ratio(self) -> float:
        total = self.frames_received
        return self.frames_dropped / total if total > 0 else 0.0

    @property
    def size(self) -> int:
        return len(self._queue)
