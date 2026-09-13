"""Android → Redis binary Pub/Sub → bounded browser queues on any worker."""
from __future__ import annotations

import asyncio
import time

import structlog
from fastapi import WebSocket
from redis.exceptions import RedisError

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.frames import VideoFrame
from backend.websocket.video_queue import VideoStreamQueue
from backend.websocket.video_transport import VideoTransport

logger = structlog.get_logger()


class VideoStreamBridge:
    def __init__(self, manager: ConnectionManager, redis=None, publisher=None) -> None:
        self.manager = manager
        self.publisher = publisher
        self._queues: dict[str, VideoStreamQueue] = {}
        self._viewer_sockets: dict[str, WebSocket] = {}
        self._sessions: dict[str, str] = {}
        self._viewer_tasks: dict[str, asyncio.Task] = {}
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
        old_stop = self._delayed_stop_tasks.pop(device_id, None)
        if old_stop:
            old_stop.cancel()
        self._pending_stops.discard(device_id)
        old_task = self._viewer_tasks.pop(device_id, None)
        if old_task:
            old_task.cancel()
        queue = self._queues[device_id] = VideoStreamQueue(device_id)
        self._viewer_sockets[device_id] = viewer_ws
        self._sessions[device_id] = session_id
        self._viewer_tasks[device_id] = asyncio.create_task(
            self._viewer_send_loop(device_id, session_id, queue, viewer_ws)
        )
        try:
            if self.transport:
                await self.transport.subscribe(device_id)
            if self._sessions.get(device_id) == session_id:
                await self.send_control(device_id, {
                    "type": "start_stream", "quality": "720p", "bitrate": 2_000_000,
                })
        except BaseException:
            await self.unregister_viewer(device_id, session_id)
            raise
        logger.info("Viewer registered", device_id=device_id, session_id=session_id)

    async def unregister_viewer(self, device_id: str, session_id: str | None = None) -> None:
        # A stale handler/send task cannot tear down a replacement viewer.
        if session_id is not None and self._sessions.get(device_id) != session_id:
            return
        task = self._viewer_tasks.pop(device_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        self._sessions.pop(device_id, None)
        self._queues.pop(device_id, None)
        self._viewer_sockets.pop(device_id, None)
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
            if device_id not in self._viewer_sockets:
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
            queue = self._publish_queues[device_id] = VideoStreamQueue(device_id)
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
                        if viewers:
                            unused_since = None
                        else:
                            unused_since = unused_since or time.monotonic()
                            if time.monotonic() - unused_since >= 2:
                                await transport.stop_if_unused(device_id)
                                unused_since = time.monotonic()
                except (RedisError, TimeoutError):
                    if time.monotonic() - last_error_log >= 30:
                        logger.warning("stream_frame_transport_unavailable", device_id=device_id)
                        last_error_log = time.monotonic()
                    await asyncio.sleep(0.5)
        finally:
            if self._publish_tasks.get(device_id) is asyncio.current_task():
                self._publish_tasks.pop(device_id, None)
                self._publish_queues.pop(device_id, None)

    async def receive_frame(self, device_id: str, frame_data: bytes) -> None:
        queue = self._queues.get(device_id)
        if queue is not None:
            await queue.put(VideoFrame(frame_data, device_id))

    async def _viewer_send_loop(self, device_id, session_id, queue, viewer_ws) -> None:
        try:
            while True:
                frame = await queue.wait()
                async with asyncio.timeout(5):
                    await viewer_ws.send_bytes(frame.data)
        except asyncio.CancelledError:
            pass
        except Exception:
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
            has_viewers = device_id in self._viewer_sockets
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
        return device_id in self._queues

    def get_drop_ratio(self, device_id: str) -> float:
        queue = self._queues.get(device_id)
        return queue.drop_ratio if queue else 0.0

    async def close(self) -> None:
        devices = list(self._sessions)
        viewer_tasks = list(self._viewer_tasks.values())
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
