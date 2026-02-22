# tests/test_ws/test_heartbeat.py
# TZ-03 SPLIT-4: Tests for HeartbeatManager.
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis

from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.heartbeat import HEARTBEAT_INTERVAL, HEARTBEAT_TIMEOUT, HeartbeatManager


class TestHeartbeatManager:
    """Unit tests for HeartbeatManager (SPLIT-4)."""

    @pytest_asyncio.fixture
    async def fake_cache(self):
        redis = FakeRedis(decode_responses=False)
        cache = DeviceStatusCache(redis)
        yield cache
        await redis.aclose()

    @pytest_asyncio.fixture
    async def ws(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest_asyncio.fixture
    async def heartbeat(self, ws, fake_cache):
        hb = HeartbeatManager(ws, "dev-1", fake_cache)
        yield hb
        await hb.stop()

    # ── constants ─────────────────────────────────────────────────────────────

    def test_heartbeat_contract_values(self):
        """Проверить что константы не были случайно изменены (MERGE-2 contract)."""
        assert HEARTBEAT_INTERVAL == 30.0
        assert HEARTBEAT_TIMEOUT == 15.0

    # ── handle_pong ───────────────────────────────────────────────────────────

    async def test_pong_updates_last_pong_timestamp(self, heartbeat):
        before = heartbeat._last_pong
        await asyncio.sleep(0.01)
        await heartbeat.handle_pong({"type": "pong", "ts": time.time()})
        assert heartbeat._last_pong > before

    async def test_pong_updates_battery_in_cache(self, heartbeat, fake_cache):
        await fake_cache.set_status(
            "dev-1",
            DeviceLiveStatus(device_id="dev-1", status="online", battery=50),
        )
        await heartbeat.handle_pong({"type": "pong", "ts": time.time(), "battery": 85})
        status = await fake_cache.get_status("dev-1")
        assert status is not None
        assert status.battery == 85

    async def test_pong_updates_cpu_usage(self, heartbeat, fake_cache):
        await fake_cache.set_status(
            "dev-1",
            DeviceLiveStatus(device_id="dev-1", status="online"),
        )
        await heartbeat.handle_pong({
            "type": "pong",
            "ts": time.time(),
            "cpu": 42.5,
            "ram_mb": 1024,
            "screen_on": True,
            "vpn_active": False,
        })
        status = await fake_cache.get_status("dev-1")
        assert status is not None
        assert status.cpu_usage == 42.5
        assert status.ram_usage_mb == 1024
        assert status.screen_on is True
        assert status.vpn_active is False

    async def test_pong_updates_last_heartbeat_timestamp(self, heartbeat, fake_cache):
        from datetime import datetime, timezone
        before = datetime.now(timezone.utc)

        await fake_cache.set_status(
            "dev-1",
            DeviceLiveStatus(device_id="dev-1", status="online"),
        )
        await heartbeat.handle_pong({"type": "pong", "ts": time.time()})

        status = await fake_cache.get_status("dev-1")
        assert status is not None
        assert status.last_heartbeat is not None
        assert status.last_heartbeat >= before

    async def test_pong_no_status_in_cache_is_noop(self, heartbeat, fake_cache):
        """Если статус не в кэше — pong не должен падать."""
        await heartbeat.handle_pong({"type": "pong", "ts": time.time(), "battery": 90})
        # No exception raised

    # ── start/stop ────────────────────────────────────────────────────────────

    async def test_start_creates_task(self, heartbeat):
        await heartbeat.start()
        assert heartbeat._task is not None
        assert not heartbeat._task.done()

    async def test_stop_cancels_task(self, heartbeat):
        await heartbeat.start()
        assert heartbeat._task is not None
        await heartbeat.stop()
        assert heartbeat._task.done()

    async def test_stop_idempotent_when_not_started(self, heartbeat):
        """stop() без start() не должен бросать исключение."""
        await heartbeat.stop()  # должно пройти без ошибок
