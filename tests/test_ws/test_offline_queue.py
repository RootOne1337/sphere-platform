# tests/test_ws/test_offline_queue.py
# Tests for OfflineCommandQueue (Redis Streams based)
from __future__ import annotations

import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.websocket.offline_queue import MAX_QUEUE_AGE_S, OfflineCommandQueue


@pytest.fixture
def mock_redis():
    """Stub async Redis with xadd, xrange, xlen, xdel, delete, expire."""
    r = AsyncMock()
    r.xadd = AsyncMock(return_value="1-0")
    r.xrange = AsyncMock(return_value=[])
    r.xlen = AsyncMock(return_value=0)
    r.xdel = AsyncMock()
    r.delete = AsyncMock()
    r.expire = AsyncMock()
    return r


@pytest.fixture
def queue(mock_redis):
    return OfflineCommandQueue(mock_redis)


class TestEnqueue:

    @pytest.mark.asyncio
    async def test_enqueue_calls_xadd(self, queue, mock_redis):
        cmd = {"type": "reboot", "id": "cmd-1"}
        ok = await queue.enqueue("device-1", cmd)

        assert ok is True
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args.args[0] == "sphere:offline_q:device-1"
        fields = call_args.args[1]
        assert json.loads(fields["cmd"]) == cmd
        assert "ts" in fields
        assert call_args.kwargs.get("maxlen") == 100

    @pytest.mark.asyncio
    async def test_enqueue_sets_expire(self, queue, mock_redis):
        await queue.enqueue("device-1", {"type": "reboot"})
        mock_redis.expire.assert_called_once_with(
            "sphere:offline_q:device-1", MAX_QUEUE_AGE_S
        )

    @pytest.mark.asyncio
    async def test_enqueue_returns_false_on_redis_error(self, queue, mock_redis):
        mock_redis.xadd.side_effect = Exception("connection lost")
        ok = await queue.enqueue("device-1", {"type": "reboot"})
        assert ok is False

    @pytest.mark.asyncio
    async def test_enqueue_returns_false_with_none_redis(self):
        q = OfflineCommandQueue(None)
        ok = await q.enqueue("device-1", {"type": "reboot"})
        assert ok is False


class TestFlush:

    @pytest.mark.asyncio
    async def test_flush_delivers_all_commands(self, queue, mock_redis):
        now = str(time.time())
        mock_redis.xrange.return_value = [
            ("1-0", {"cmd": '{"type":"reboot","id":"a"}', "ts": now}),
            ("2-0", {"cmd": '{"type":"shell","id":"b","cmd":"ls"}', "ts": now}),
        ]
        mock_redis.xlen.return_value = 0

        send_fn = AsyncMock(return_value=True)
        delivered = await queue.flush("device-1", send_fn)

        assert delivered == 2
        assert send_fn.call_count == 2
        mock_redis.xdel.assert_called_once()
        mock_redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_skips_expired_commands(self, queue, mock_redis):
        expired_ts = str(time.time() - MAX_QUEUE_AGE_S - 100)
        mock_redis.xrange.return_value = [
            ("1-0", {"cmd": '{"type":"reboot"}', "ts": expired_ts}),
        ]
        mock_redis.xlen.return_value = 0

        send_fn = AsyncMock(return_value=True)
        delivered = await queue.flush("device-1", send_fn)

        assert delivered == 0
        send_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_stops_on_send_failure(self, queue, mock_redis):
        """If device goes offline mid-flush, stop delivering."""
        now = str(time.time())
        mock_redis.xrange.return_value = [
            ("1-0", {"cmd": '{"type":"a"}', "ts": now}),
            ("2-0", {"cmd": '{"type":"b"}', "ts": now}),
        ]
        mock_redis.xlen.return_value = 1

        send_fn = AsyncMock(side_effect=[True, False])
        delivered = await queue.flush("device-1", send_fn)

        assert delivered == 1

    @pytest.mark.asyncio
    async def test_flush_returns_zero_when_empty(self, queue, mock_redis):
        mock_redis.xrange.return_value = []
        delivered = await queue.flush("device-1", AsyncMock())
        assert delivered == 0

    @pytest.mark.asyncio
    async def test_flush_returns_zero_with_none_redis(self):
        q = OfflineCommandQueue(None)
        delivered = await q.flush("device-1", AsyncMock())
        assert delivered == 0


class TestQueueSize:

    @pytest.mark.asyncio
    async def test_queue_size_returns_xlen(self, queue, mock_redis):
        mock_redis.xlen.return_value = 42
        assert await queue.queue_size("device-1") == 42

    @pytest.mark.asyncio
    async def test_queue_size_returns_zero_on_error(self, queue, mock_redis):
        mock_redis.xlen.side_effect = Exception("fail")
        assert await queue.queue_size("device-1") == 0

    @pytest.mark.asyncio
    async def test_queue_size_with_none_redis(self):
        q = OfflineCommandQueue(None)
        assert await q.queue_size("device-1") == 0


class TestClear:

    @pytest.mark.asyncio
    async def test_clear_deletes_stream(self, queue, mock_redis):
        await queue.clear("device-1")
        mock_redis.delete.assert_called_once_with("sphere:offline_q:device-1")

    @pytest.mark.asyncio
    async def test_clear_with_none_redis(self):
        q = OfflineCommandQueue(None)
        await q.clear("device-1")  # should not raise
