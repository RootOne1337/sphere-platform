# backend/websocket/offline_queue.py
# Offline Command Queue — Redis Streams based pending command storage.
# When device is offline, commands are queued. On reconnect, they are flushed.
from __future__ import annotations

import json
import time

import structlog

logger = structlog.get_logger()

# Max commands per device in offline queue (prevent unbounded growth)
MAX_QUEUE_SIZE = 100
# Max age for queued commands in seconds (24h)
MAX_QUEUE_AGE_S = 86400


class OfflineCommandQueue:
    """
    Redis Streams-backed offline command queue.

    When send_command_to_device fails (device offline), the command is
    queued via `enqueue()`. When the device reconnects, `flush()` is
    called to deliver all pending commands in order.

    Stream key: `sphere:offline_q:{device_id}`
    """

    def __init__(self, redis) -> None:
        self.redis = redis

    def _stream_key(self, device_id: str) -> str:
        return f"sphere:offline_q:{device_id}"

    async def enqueue(self, device_id: str, command: dict) -> bool:
        """Queue a command for an offline device. Returns True if queued."""
        if self.redis is None:
            return False
        try:
            key = self._stream_key(device_id)
            payload = json.dumps(command)
            await self.redis.xadd(
                key,
                {"cmd": payload, "ts": str(time.time())},
                maxlen=MAX_QUEUE_SIZE,
            )
            # Auto-expire the stream after MAX_QUEUE_AGE_S
            await self.redis.expire(key, MAX_QUEUE_AGE_S)
            logger.info("Command queued for offline device", device_id=device_id)
            return True
        except Exception as e:
            logger.warning("Failed to enqueue command", device_id=device_id, error=str(e))
            return False

    async def flush(self, device_id: str, send_fn) -> int:
        """
        Flush all pending commands to the device.
        `send_fn` is an async callable (command: dict) -> bool that actually
        delivers the command via WebSocket.
        Returns number of delivered commands.
        """
        if self.redis is None:
            return 0

        key = self._stream_key(device_id)
        delivered = 0
        now = time.time()

        try:
            # Read all messages from the stream
            messages = await self.redis.xrange(key, min="-", max="+")
            if not messages:
                return 0

            ids_to_ack: list[str] = []
            for msg_id, fields in messages:
                cmd_json = fields.get("cmd")
                ts = float(fields.get("ts", "0"))

                # Skip expired commands
                if now - ts > MAX_QUEUE_AGE_S:
                    ids_to_ack.append(msg_id)
                    continue

                try:
                    command = json.loads(cmd_json)
                    ok = await send_fn(command)
                    if ok:
                        delivered += 1
                        ids_to_ack.append(msg_id)
                    else:
                        # Device went offline again mid-flush — stop
                        break
                except Exception as e:
                    logger.warning(
                        "Flush command failed", device_id=device_id, error=str(e)
                    )
                    break

            # Delete delivered messages
            if ids_to_ack:
                await self.redis.xdel(key, *ids_to_ack)

            # If all messages delivered, clean up the stream key
            remaining = await self.redis.xlen(key)
            if remaining == 0:
                await self.redis.delete(key)

            if delivered:
                logger.info(
                    "Flushed offline queue",
                    device_id=device_id,
                    delivered=delivered,
                )
        except Exception as e:
            logger.warning("Flush failed", device_id=device_id, error=str(e))

        return delivered

    async def queue_size(self, device_id: str) -> int:
        """Get number of pending commands for a device."""
        if self.redis is None:
            return 0
        try:
            return await self.redis.xlen(self._stream_key(device_id))
        except Exception:
            return 0

    async def clear(self, device_id: str) -> None:
        """Clear all pending commands for a device."""
        if self.redis is None:
            return
        try:
            await self.redis.delete(self._stream_key(device_id))
        except Exception:
            pass


# Singleton
_offline_queue: OfflineCommandQueue | None = None


def get_offline_queue() -> OfflineCommandQueue | None:
    return _offline_queue


async def _startup_offline_queue() -> None:
    global _offline_queue
    from backend.database.redis_client import redis
    if redis:
        _offline_queue = OfflineCommandQueue(redis)


from backend.core.lifespan_registry import register_startup  # noqa: E402

register_startup("offline_queue", _startup_offline_queue)
