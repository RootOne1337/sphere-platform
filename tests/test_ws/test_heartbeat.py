# tests/test_ws/test_heartbeat.py
# TZ-03 SPLIT-4: Tests for HeartbeatManager.
from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

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
        heartbeat._last_pong = asyncio.get_running_loop().time() - 10
        before = heartbeat._last_pong
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

    async def test_pong_updates_agent_build_metadata(self, heartbeat, fake_cache):
        await fake_cache.set_status(
            "dev-1",
            DeviceLiveStatus(device_id="dev-1", status="online"),
        )
        await heartbeat.handle_pong({
            "type": "pong",
            "ts": time.time(),
            "agent_version": "1.2.20-dev",
            "agent_version_code": 10220,
        })

        status = await fake_cache.get_status("dev-1")
        assert status is not None
        assert status.agent_version == "1.2.20-dev"
        assert status.agent_version_code == 10220

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

    async def test_pong_persists_sanitized_stream_snapshot_with_session_identity(
        self, ws, fake_cache
    ):
        heartbeat = HeartbeatManager(ws, "dev-stream", fake_cache, session_id="ws-session-7")
        await heartbeat.handle_pong({
            "type": "pong",
            "ts": time.time(),
            "stream": {
                "schema_version": 2,
                "active": True,
                "stage": "capture_encoder_ws_queue",
                "capture_fps": 16,
                "render_fps": 15,
                "capture_frames_total": 320,
                "rendered_frames_total": 300,
                "capture_read_failures_total": 1,
                "render_failures_total": 2,
                "encoder_errors_total": 0,
                "frame_throttle_drops_total": 12,
                "encoder_fps": 15,
                "encoded_frames_total": 300,
                "encoded_bytes_total": 1_000_000,
                "key_frame_ratio": 0.05,
                "ws_queue_attempts_total": 305,
                "ws_queue_accepted_total": 304,
                "ws_queue_rejected_total": 1,
                "ws_queue_accepted_bytes_total": 990_000,
                "private_token": "must-not-be-persisted",
            },
        })

        snapshot = await fake_cache.get_stream_diagnostics("dev-stream")
        assert snapshot is not None
        assert snapshot.agent_session_id == "ws-session-7"
        assert snapshot.telemetry.capture_fps == 16
        assert "private_token" not in snapshot.telemetry.model_dump()
        assert await fake_cache.redis.ttl("device:stream-diagnostics:dev-stream") > 0

        await heartbeat.handle_pong({"type": "pong", "ts": time.time()})
        assert await fake_cache.get_stream_diagnostics("dev-stream") is None

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
