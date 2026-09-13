"""Binary Redis transport, isolated from the command Pub/Sub reader.

One subscription connection per worker; browser writes run in separate bounded
queues. Subscribe acknowledgements precede start commands. No video is persisted.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

import structlog
from redis.asyncio.client import PubSub
from redis.exceptions import RedisError

from backend.websocket.channels import ChannelPattern

logger = structlog.get_logger()

# A new subscriber publishes start only AFTER its subscribe acknowledgement.
STOP_IF_UNUSED = """
local viewers = redis.call('PUBSUB', 'NUMSUB', ARGV[1])
if viewers[2] == 0 then
    return redis.call('PUBLISH', ARGV[2], ARGV[3])
end
return -1
"""


class VideoTransport:
    def __init__(self, redis, receive: Callable[[str, bytes], Awaitable[None]], control) -> None:
        self.redis = redis
        self.receive = receive
        self.control = control
        self._channels: dict[str, asyncio.Event] = {}
        self._established: set[str] = set()
        self._lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._pubsub: PubSub | None = None
        self._task: asyncio.Task | None = None

    async def subscribe(self, device_id: str) -> None:
        channel = ChannelPattern.video_stream(device_id)
        async with self._lock:
            ready = self._channels.get(channel)
            if ready is None:
                ready = self._channels[channel] = asyncio.Event()
                if self._pubsub is not None:
                    await self._pubsub.subscribe(channel)
            self._changed.set()
            if self._task is None:
                self._task = asyncio.create_task(self._listen())
        async with asyncio.timeout(5):
            await ready.wait()

    async def unsubscribe(self, device_id: str) -> None:
        channel = ChannelPattern.video_stream(device_id)
        async with self._lock:
            self._channels.pop(channel, None)
            self._established.discard(channel)
            if self._pubsub is not None:
                await self._pubsub.unsubscribe(channel)

    async def _listen(self) -> None:
        backoff = 0.25
        try:
            while True:
                try:
                    async with self._lock:
                        if self._pubsub is None and self._channels:
                            fresh: PubSub = self.redis.pubsub()
                            self._pubsub = fresh
                            await fresh.subscribe(*self._channels)
                        ps = self._pubsub
                        if not self._channels:
                            self._changed.clear()
                    if not self._channels:
                        await self._changed.wait()
                        continue
                    assert ps is not None
                    while ps.subscribed:
                        # ImageReader may emit nothing for a static screen.
                        # listen() inherits the Redis request socket_timeout;
                        # redis-py then reconnects and re-subscribes every 5 s,
                        # which incorrectly restarts the healthy capture below.
                        # A Pub/Sub poll timeout returns None without reconnect.
                        message = await ps.get_message(timeout=1.0)
                        if message is None:
                            continue
                        channel = message["channel"].decode()
                        device = channel.removeprefix("sphere:stream:video:")
                        if channel not in self._channels:
                            continue
                        if message["type"] == "subscribe":
                            self._channels[channel].set()
                            if channel in self._established:
                                # Capture may have stopped while the transport
                                # was unavailable. Recover it as well as the IDR.
                                await self.control(device, {
                                    "type": "start_stream", "quality": "720p", "bitrate": 2_000_000,
                                })
                                await self.control(device, {"type": "viewer_connected"})
                            self._established.add(channel)
                            backoff = 0.25
                        elif message["type"] == "message":
                            await self.receive(device, message["data"])
                except (RedisError, OSError, TimeoutError):
                    logger.warning("stream_video_transport_recovering", retry_seconds=backoff)
                    async with self._lock:
                        for event in self._channels.values():
                            event.clear()
                        if self._pubsub is not None:
                            await self._pubsub.aclose()
                            self._pubsub = None
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 5)
        finally:
            if self._pubsub is not None:
                await self._pubsub.aclose()
                self._pubsub = None

    async def publish(self, device_id: str, data: bytes) -> int:
        return await self.redis.publish(ChannelPattern.video_stream(device_id), data)

    async def has_viewers(self, device_id: str) -> bool:
        result = await self.redis.pubsub_numsub(ChannelPattern.video_stream(device_id))
        return bool(result[0][1])

    async def stop_if_unused(self, device_id: str) -> bool:
        return await self.redis.eval(
            STOP_IF_UNUSED, 0, ChannelPattern.video_stream(device_id),
            ChannelPattern.agent_cmd(device_id), json.dumps({"type": "stop_stream"}),
        ) > 0

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
