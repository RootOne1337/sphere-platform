"""Android → Redis binary Pub/Sub → bounded browser queues on any worker."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from weakref import WeakValueDictionary

import structlog
from fastapi import WebSocket
from redis.exceptions import RedisError

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.frames import VideoFrame
from backend.websocket.stream_observability import (
    record_active_viewer_delta,
    record_redis_publish,
    record_redis_publish_failure,
    record_viewer_send,
    record_viewer_send_failure,
)
from backend.websocket.video_queue import VideoStreamQueue
from backend.websocket.video_transport import VideoTransport

logger = structlog.get_logger()


@dataclass
class ViewerSession:
    queue: VideoStreamQueue
    socket: WebSocket
    task: asyncio.Task


class VideoStreamBridge:
    def __init__(self, manager: ConnectionManager, redis=None, publisher=None) -> None:
        self.manager = manager
        self.publisher = publisher
        self._viewers: dict[str, dict[str, ViewerSession]] = {}
        # Callers (including lock waiters) retain a strong reference. Once a
        # device is idle its lock disappears, without an ever-growing registry.
        self._device_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self._closed = False
        self._delayed_stop_tasks: dict[str, asyncio.Task] = {}
        self._pending_stops: set[str] = set()
        self._publish_queues: dict[str, VideoStreamQueue] = {}
        self._publish_tasks: dict[str, asyncio.Task] = {}
        self.transport = VideoTransport(redis, self.receive_frame, self.send_control) if redis is not None else None

    async def send_control(self, device_id: str, command: dict) -> bool:
        if self.publisher is not None:
            async with asyncio.timeout(2):
                return await self.publisher.send_command_live(device_id, command)
        return await self.manager.send_to_device(device_id, command)

    async def register_viewer(self, device_id: str, viewer_ws: WebSocket, session_id: str) -> None:
        async with self._device_lock(device_id):
            if self._closed:
                raise ConnectionError("Video bridge is closed")
            viewers = self._viewers.setdefault(device_id, {})
            if session_id in viewers:
                raise ValueError("Viewer session already registered")
            old_stop = self._delayed_stop_tasks.pop(device_id, None)
            if old_stop:
                old_stop.cancel()
            self._pending_stops.discard(device_id)
            queue = VideoStreamQueue(device_id)
            task = asyncio.create_task(self._viewer_send_loop(device_id, session_id, queue, viewer_ws))
            viewers[session_id] = ViewerSession(queue, viewer_ws, task)
            record_active_viewer_delta(device_id, 1)
            try:
                if self.transport and len(viewers) == 1:
                    await self.transport.subscribe(device_id)
                sent = await self.send_control(device_id, {
                    "type": "start_stream", "quality": "720p", "bitrate": 2_000_000,
                })
                if not sent:
                    logger.warning("stream_start_unavailable", device_id=device_id, session_id=session_id)
                    raise ConnectionError("Capture command transport unavailable")
            except BaseException:
                await self._unregister_viewer_locked(device_id, session_id)
                raise
        logger.info("Viewer registered", device_id=device_id, session_id=session_id)

    def _device_lock(self, device_id: str) -> asyncio.Lock:
        lock = self._device_locks.get(device_id)
        if lock is None:
            lock = self._device_locks[device_id] = asyncio.Lock()
        return lock

    async def unregister_viewer(self, device_id: str, session_id: str | None = None) -> None:
        async with self._device_lock(device_id):
            await self._unregister_viewer_locked(device_id, session_id)

    async def _unregister_viewer_locked(self, device_id: str, session_id: str | None) -> None:
        viewers = self._viewers.get(device_id)
        if not viewers or (session_id is not None and session_id not in viewers):
            return
        sessions = [session_id] if session_id is not None else list(viewers)
        for session in sessions:
            viewer = viewers.pop(session)
            record_active_viewer_delta(device_id, -1)
            if viewer.task is not asyncio.current_task():
                viewer.task.cancel()
        if viewers:
            return
        self._viewers.pop(device_id, None)
        try:
            if self.transport:
                await self.transport.unsubscribe(device_id)
        except (RedisError, TimeoutError):
            logger.warning("stream_unsubscribe_pending_recovery", device_id=device_id)
        finally:
            old_stop = self._delayed_stop_tasks.pop(device_id, None)
            if old_stop:
                old_stop.cancel()
            self._delayed_stop_tasks[device_id] = asyncio.create_task(self._delayed_stop(device_id))

    async def _delayed_stop(self, device_id: str) -> None:
        try:
            await asyncio.sleep(2)
            if device_id not in self._viewers:
                if self.transport:
                    await self.transport.stop_if_unused(device_id)
                elif not await self.manager.send_to_device(device_id, {"type": "stop_stream"}):
                    self._pending_stops.add(device_id)
        except (RedisError, TimeoutError):
            # Agent frame publication also detects a vanished viewer worker.
            logger.warning("stream_stop_pending_transport_recovery", device_id=device_id)
        finally:
            if self._delayed_stop_tasks.get(device_id) is asyncio.current_task():
                self._delayed_stop_tasks.pop(device_id, None)

    async def handle_agent_frame(self, device_id: str, frame_data: bytes) -> None:
        if not self.transport:
            await self.receive_frame(device_id, frame_data)
            return
        queue = self._publish_queues.get(device_id)
        if queue is None:
            queue = self._publish_queues[device_id] = VideoStreamQueue(
                device_id, queue_stage="agent_to_redis",
            )
            self._publish_tasks[device_id] = asyncio.create_task(self._publish_loop(device_id, queue))
        await queue.put(VideoFrame(frame_data, device_id))

    async def _publish_loop(self, device_id: str, queue: VideoStreamQueue) -> None:
        transport = self.transport
        assert transport is not None
        unused_since = None
        last_error_log = 0.0
        try:
            while True:
                try:
                    async with asyncio.timeout(10):
                        frame = await queue.wait()
                except TimeoutError:
                    return
                try:
                    async with asyncio.timeout(1):
                        viewers = await transport.publish(device_id, frame.data)
                        record_redis_publish(device_id, len(frame.data), viewers)
                        if viewers:
                            unused_since = None
                        else:
                            unused_since = unused_since or time.monotonic()
                            if time.monotonic() - unused_since >= 2:
                                await transport.stop_if_unused(device_id)
                                unused_since = time.monotonic()
                except (RedisError, TimeoutError):
                    record_redis_publish_failure(device_id)
                    if time.monotonic() - last_error_log >= 30:
                        logger.warning("stream_frame_transport_unavailable", device_id=device_id)
                        last_error_log = time.monotonic()
                    await asyncio.sleep(0.5)
        finally:
            if self._publish_tasks.get(device_id) is asyncio.current_task():
                self._publish_tasks.pop(device_id, None)
                self._publish_queues.pop(device_id, None)

    async def receive_frame(self, device_id: str, frame_data: bytes) -> None:
        # Each viewer owns its backpressure; frame bytes are shared, not copied.
        frame = VideoFrame(frame_data, device_id)
        for viewer in tuple(self._viewers.get(device_id, {}).values()):
            await viewer.queue.put(frame)

    async def _viewer_send_loop(self, device_id, session_id, queue, viewer_ws) -> None:
        try:
            while True:
                frame = await queue.wait()
                async with asyncio.timeout(5):
                    await viewer_ws.send_bytes(frame.data)
                record_viewer_send(device_id, len(frame.data))
        except asyncio.CancelledError:
            pass
        except Exception:
            record_viewer_send_failure(device_id)
            logger.warning("stream_viewer_send_failed", device_id=device_id, session_id=session_id)
            await self.unregister_viewer(device_id, session_id)
            try:
                async with asyncio.timeout(1):
                    await viewer_ws.close(code=1013, reason="stream_send_failed")
            except Exception:
                pass

    async def resume_stream_for_device(self, device_id: str) -> None:
        if self.transport:
            has_viewers = await self.transport.has_viewers(device_id)
        else:
            has_viewers = device_id in self._viewers
            if not has_viewers and device_id not in self._pending_stops:
                return
        if not has_viewers:
            if self.transport:
                await self.transport.stop_if_unused(device_id)
                return
            if await self.manager.send_to_device(device_id, {"type": "stop_stream"}):
                self._pending_stops.discard(device_id)
            return
        await self.manager.send_to_device(device_id, {
            "type": "start_stream", "quality": "720p", "bitrate": 2_000_000,
        })
        await self.manager.send_to_device(device_id, {"type": "viewer_connected"})

    def is_streaming(self, device_id: str) -> bool:
        """Local viewer presence only; not a frame-delivery acknowledgement."""
        return device_id in self._viewers

    def get_drop_ratio(self, device_id: str) -> float:
        queues = [v.queue for v in self._viewers.get(device_id, {}).values()]
        received = sum(q.frames_received for q in queues)
        return sum(q.frames_dropped for q in queues) / received if received else 0.0

    async def close(self) -> None:
        self._closed = True
        devices = list(self._viewers)
        viewer_tasks = [v.task for viewers in self._viewers.values() for v in viewers.values()]
        for device in devices:
            await self.unregister_viewer(device)
        if self.transport:
            await self.transport.close()
        tasks = [*viewer_tasks, *self._delayed_stop_tasks.values(), *self._publish_tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._publish_queues.clear()
        if self.transport:
            for device in devices:
                try:
                    async with asyncio.timeout(1):
                        await self.transport.stop_if_unused(device)
                except (RedisError, TimeoutError):
                    pass


_stream_bridge: VideoStreamBridge | None = None


def get_stream_bridge() -> VideoStreamBridge | None:
    return _stream_bridge


def init_stream_bridge(manager: ConnectionManager) -> VideoStreamBridge:
    from backend.database.redis_client import redis_binary
    from backend.websocket.pubsub_router import get_pubsub_publisher

    global _stream_bridge
    _stream_bridge = VideoStreamBridge(manager, redis_binary, get_pubsub_publisher())
    return _stream_bridge
