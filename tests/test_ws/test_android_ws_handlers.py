# tests/test_ws/test_android_ws_handlers.py
"""
Unit tests for Android WebSocket message handler functions.

These test the individual handler functions in isolation — no real WebSocket
connection needed.  Each handler processes a specific message type and either
updates the Redis status cache, publishes to Redis pub/sub, or routes to the
stream bridge.

Enterprise rationale
--------------------
- Partial telemetry updates MUST preserve untouched cache fields (no regression
  zero-out of battery when only cpu is reported).
- Missing cache entry → no exception (device may reconnect before cache is
  populated — handler must be defensive).
- command_result publishes to the exact channel
  sphere:agent:result:{device}:{command_id}; consumer (send_command_wait_result)
  depends on this format.
- Redis failure → warning log, never raised to the WS receive loop — a Redis
  outage must not disconnect the device.
- device_event publisher exception is swallowed — fleet events are best-effort
  and must never kill the agent connection.
- Binary frame → stream bridge exceptions are swallowed — H.264 stream errors
  must not disconnect the Android agent.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.ws.android.router import (
    handle_agent_binary,
    handle_command_result,
    handle_device_event,
    handle_telemetry,
)
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache

DEVICE_ID = "550e8400-e29b-41d4-a716-446655440000"
ORG_ID = "org-00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def binary_redis():
    """FakeRedis in raw-bytes mode (required by DeviceStatusCache / msgpack)."""
    from fakeredis.aioredis import FakeRedis
    return FakeRedis()


@pytest.fixture()
def status_cache(binary_redis):
    return DeviceStatusCache(binary_redis)


# ===========================================================================
# handle_telemetry
# ===========================================================================

class TestHandleTelemetry:
    async def test_updates_battery(self, status_cache):
        initial = DeviceLiveStatus(device_id=DEVICE_ID, status="online", battery=50)
        await status_cache.set_status(DEVICE_ID, initial)

        await handle_telemetry(
            DEVICE_ID,
            {"type": "telemetry", "battery": 85},
            status_cache,
        )

        updated = await status_cache.get_status(DEVICE_ID)
        assert updated is not None
        assert updated.battery == 85

    async def test_updates_cpu_and_ram(self, status_cache):
        initial = DeviceLiveStatus(device_id=DEVICE_ID, status="online")
        await status_cache.set_status(DEVICE_ID, initial)

        await handle_telemetry(
            DEVICE_ID,
            {"type": "telemetry", "cpu": 42.5, "ram_mb": 1024},
            status_cache,
        )

        updated = await status_cache.get_status(DEVICE_ID)
        assert updated.cpu_usage == 42.5
        assert updated.ram_usage_mb == 1024

    async def test_updates_screen_on_and_vpn(self, status_cache):
        initial = DeviceLiveStatus(device_id=DEVICE_ID, status="online")
        await status_cache.set_status(DEVICE_ID, initial)

        await handle_telemetry(
            DEVICE_ID,
            {"type": "telemetry", "screen_on": True, "vpn_active": True},
            status_cache,
        )

        updated = await status_cache.get_status(DEVICE_ID)
        assert updated.screen_on is True
        assert updated.vpn_active is True

    async def test_no_cache_entry_is_noop(self, status_cache):
        """Missing status entry → no exception raised, no entry created."""
        await handle_telemetry(
            DEVICE_ID,
            {"type": "telemetry", "battery": 99},
            status_cache,
        )
        result = await status_cache.get_status(DEVICE_ID)
        assert result is None

    async def test_partial_update_preserves_other_fields(self, status_cache):
        """Only fields present in the message are updated; others preserved."""
        initial = DeviceLiveStatus(
            device_id=DEVICE_ID,
            status="online",
            battery=80,
            cpu_usage=10.0,
        )
        await status_cache.set_status(DEVICE_ID, initial)

        await handle_telemetry(
            DEVICE_ID,
            {"type": "telemetry", "battery": 30},
            status_cache,
        )

        updated = await status_cache.get_status(DEVICE_ID)
        assert updated.battery == 30
        assert updated.cpu_usage == 10.0  # must not be zeroed out

    async def test_empty_payload_is_noop(self, status_cache):
        """Telemetry message with no fields → no change to cache."""
        initial = DeviceLiveStatus(device_id=DEVICE_ID, status="online", battery=70)
        await status_cache.set_status(DEVICE_ID, initial)

        await handle_telemetry(DEVICE_ID, {"type": "telemetry"}, status_cache)

        updated = await status_cache.get_status(DEVICE_ID)
        assert updated.battery == 70


# ===========================================================================
# handle_command_result
# ===========================================================================

class TestHandleCommandResult:
    async def test_publishes_to_correct_channel(self):
        """Verified channel format: sphere:agent:result:{device_id}:{command_id}."""
        calls: list[dict] = []

        async def _fake_publish(channel, payload):
            calls.append({"channel": channel, "payload": payload})
            return 1

        mock_redis = MagicMock()
        mock_redis.publish = _fake_publish

        with patch("backend.database.redis_client.redis", mock_redis):
            await handle_command_result(
                DEVICE_ID,
                ORG_ID,
                {"type": "command_result", "command_id": "cmd-abc", "status": "completed"},
            )

        assert len(calls) == 1
        expected = f"sphere:agent:result:{DEVICE_ID}:cmd-abc"
        assert calls[0]["channel"] == expected

    async def test_published_payload_is_valid_json(self):
        """Payload must survive JSON round-trip (send_command_wait_result parses it)."""
        payload_received: list[str] = []

        async def _capture_publish(channel, payload):
            payload_received.append(payload)
            return 1

        mock_redis = MagicMock()
        mock_redis.publish = _capture_publish

        msg = {"type": "command_result", "command_id": "cmd-1", "status": "completed", "result": {"exit_code": 0}}
        with patch("backend.database.redis_client.redis", mock_redis):
            await handle_command_result(DEVICE_ID, ORG_ID, msg)

        assert len(payload_received) == 1
        decoded = json.loads(payload_received[0])
        assert decoded["command_id"] == "cmd-1"
        assert decoded["result"]["exit_code"] == 0

    async def test_id_field_used_as_fallback_when_no_command_id(self):
        """`id` field is the fallback when `command_id` is absent."""
        channels: list[str] = []

        async def _capture(channel, _payload):
            channels.append(channel)
            return 1

        mock_redis = MagicMock()
        mock_redis.publish = _capture

        with patch("backend.database.redis_client.redis", mock_redis):
            await handle_command_result(
                DEVICE_ID,
                ORG_ID,
                {"type": "command_result", "id": "fallback-99"},
            )

        assert len(channels) == 1
        assert "fallback-99" in channels[0]

    async def test_missing_command_id_and_id_is_noop(self):
        """No command_id and no id → no Redis publish."""
        mock_redis = AsyncMock()

        with patch("backend.database.redis_client.redis", mock_redis):
            await handle_command_result(DEVICE_ID, ORG_ID, {"type": "command_result"})

        mock_redis.publish.assert_not_called()

    async def test_redis_exception_does_not_propagate(self):
        """Redis publish failure → warning logged, must not raise (connection stability)."""
        mock_redis = AsyncMock()
        mock_redis.publish = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("backend.database.redis_client.redis", mock_redis):
            # Соединение должно оставаться живым — Redis outage не должен роняться
            await handle_command_result(
                DEVICE_ID,
                ORG_ID,
                {"type": "command_result", "command_id": "cmd-fail"},
            )

    async def test_none_redis_is_noop(self):
        """redis=None (e.g. cold start) → no exception."""
        with patch("backend.database.redis_client.redis", None):
            await handle_command_result(
                DEVICE_ID,
                ORG_ID,
                {"type": "command_result", "command_id": "cmd-1"},
            )


# ===========================================================================
# handle_device_event
# ===========================================================================

class TestHandleDeviceEvent:
    async def test_emits_fleet_event_with_correct_device_id(self):
        """FleetEvent must carry the correct device_id."""
        mock_publisher = AsyncMock()

        with patch(
            "backend.websocket.event_publisher.get_event_publisher",
            return_value=mock_publisher,
        ):
            await handle_device_event(
                DEVICE_ID,
                {"type": "event", "org_id": "org-1", "status": "busy"},
            )

        mock_publisher.emit.assert_called_once()
        fleet_event = mock_publisher.emit.call_args[0][0]
        assert fleet_event.device_id == DEVICE_ID

    async def test_no_publisher_is_noop(self):
        """No event publisher initialised → no exception."""
        with patch(
            "backend.websocket.event_publisher.get_event_publisher",
            return_value=None,
        ):
            await handle_device_event(DEVICE_ID, {"type": "event"})

    async def test_publisher_exception_is_swallowed(self):
        """EventPublisher.emit raises → logged as debug, not re-raised."""
        mock_publisher = AsyncMock()
        mock_publisher.emit = AsyncMock(side_effect=RuntimeError("publish failed"))

        with patch(
            "backend.websocket.event_publisher.get_event_publisher",
            return_value=mock_publisher,
        ):
            # Must not raise — fleet events are best-effort
            await handle_device_event(DEVICE_ID, {"type": "event"})

    async def test_event_type_is_device_status_change(self):
        """Incoming device events map to DEVICE_STATUS_CHANGE event type."""
        from backend.schemas.events import EventType

        captured: list = []

        async def _capture(event):
            captured.append(event)

        mock_publisher = MagicMock()
        mock_publisher.emit = _capture

        with patch(
            "backend.websocket.event_publisher.get_event_publisher",
            return_value=mock_publisher,
        ):
            await handle_device_event(
                DEVICE_ID,
                {"type": "event", "org_id": "some-org"},
            )

        assert len(captured) == 1
        assert captured[0].event_type == EventType.DEVICE_STATUS_CHANGE


# ===========================================================================
# handle_agent_binary
# ===========================================================================

class TestHandleAgentBinary:
    _SAMPLE_FRAME = b"\x00\x00\x00\x01\x65" + b"\xAB" * 200  # NAL IDR start code

    async def test_routes_frame_to_bridge(self):
        """Frame bytes forwarded to stream bridge handle_agent_frame."""
        mock_bridge = AsyncMock()

        with patch(
            "backend.websocket.stream_bridge.get_stream_bridge",
            return_value=mock_bridge,
        ):
            await handle_agent_binary(DEVICE_ID, self._SAMPLE_FRAME, MagicMock())

        mock_bridge.handle_agent_frame.assert_called_once_with(
            DEVICE_ID, self._SAMPLE_FRAME
        )

    async def test_no_bridge_is_noop(self):
        """Stream bridge not yet initialised → no exception."""
        with patch(
            "backend.websocket.stream_bridge.get_stream_bridge",
            return_value=None,
        ):
            await handle_agent_binary(DEVICE_ID, self._SAMPLE_FRAME, MagicMock())

    async def test_bridge_exception_is_swallowed(self):
        """Bridge.handle_agent_frame raises → logged as debug, not re-raised."""
        mock_bridge = AsyncMock()
        mock_bridge.handle_agent_frame = AsyncMock(
            side_effect=RuntimeError("queue full")
        )

        with patch(
            "backend.websocket.stream_bridge.get_stream_bridge",
            return_value=mock_bridge,
        ):
            # Must not raise — stream failure must not disconnect Android agent
            await handle_agent_binary(DEVICE_ID, self._SAMPLE_FRAME, MagicMock())

    async def test_empty_bytes_handled_gracefully(self):
        """Zero-length frame (malformed) does not crash the handler."""
        mock_bridge = AsyncMock()

        with patch(
            "backend.websocket.stream_bridge.get_stream_bridge",
            return_value=mock_bridge,
        ):
            await handle_agent_binary(DEVICE_ID, b"", MagicMock())

        mock_bridge.handle_agent_frame.assert_called_once_with(DEVICE_ID, b"")
