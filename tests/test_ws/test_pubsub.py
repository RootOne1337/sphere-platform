# tests/test_ws/test_pubsub.py
# TZ-03 SPLIT-2: Tests for PubSubPublisher, PubSubRouter, and ChannelPattern.
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest_asyncio

from backend.websocket.channels import ChannelPattern
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter


class TestChannelPattern:
    """Unit tests for channel naming convention."""

    def test_agent_cmd_channel(self):
        ch = ChannelPattern.agent_cmd("device-123")
        assert ch == "sphere:agent:cmd:device-123"

    def test_org_events_channel(self):
        ch = ChannelPattern.org_events("org-abc")
        assert ch == "sphere:org:events:org-abc"

    def test_video_stream_channel(self):
        ch = ChannelPattern.video_stream("dev-1")
        assert ch == "sphere:stream:video:dev-1"

    def test_agent_result_pattern(self):
        pattern = ChannelPattern.agent_result_pattern("dev-1")
        assert pattern == "sphere:agent:result:dev-1:*"

    def test_device_id_with_colon_safe(self):
        """device_id с двоеточием (ADB TCP: 192.168.1.1:5555) — removeprefix безопасен."""
        device_id = "192.168.1.1:5555"
        ch = ChannelPattern.agent_cmd(device_id)
        # removeprefix должен вернуть именно device_id с двоеточием
        extracted = ch.removeprefix("sphere:agent:cmd:")
        assert extracted == device_id

    def test_no_key_collisions(self):
        """Проверить что sphere:* каналы не пересекаются с data ключами TZ-02."""
        agent_cmd = ChannelPattern.agent_cmd("dev")
        org_events = ChannelPattern.org_events("org")
        assert agent_cmd.startswith("sphere:")
        assert org_events.startswith("sphere:")
        # Data ключи TZ-02 используют другой префикс
        assert not agent_cmd.startswith("device:status:")


class TestPubSubPublisher:
    """Unit tests for PubSubPublisher."""

    @pytest_asyncio.fixture
    async def redis_mock(self):
        redis = AsyncMock()
        redis.publish = AsyncMock(return_value=1)
        return redis

    @pytest_asyncio.fixture
    async def publisher(self, redis_mock):
        return PubSubPublisher(redis_mock)

    async def test_send_command_to_device_returns_true_when_subscribers(
        self, publisher, redis_mock
    ):
        redis_mock.publish.return_value = 1
        result = await publisher.send_command_to_device("dev-1", {"type": "click"})
        assert result is True

    async def test_send_command_to_device_returns_false_when_no_subscribers(
        self, publisher, redis_mock
    ):
        redis_mock.publish.return_value = 0
        result = await publisher.send_command_to_device("dev-1", {"type": "click"})
        assert result is False

    async def test_send_command_uses_correct_channel(self, publisher, redis_mock):
        await publisher.send_command_to_device("my-device", {"cmd": "tap"})
        redis_mock.publish.assert_called_once()
        channel, _ = redis_mock.publish.call_args.args
        assert channel == "sphere:agent:cmd:my-device"

    async def test_send_command_payload_is_json(self, publisher, redis_mock):
        cmd = {"type": "tap", "x": 100, "y": 200}
        await publisher.send_command_to_device("dev-1", cmd)
        _, payload = redis_mock.publish.call_args.args
        assert json.loads(payload) == cmd

    async def test_broadcast_org_event(self, publisher, redis_mock):
        redis_mock.publish.return_value = 3
        count = await publisher.broadcast_org_event("org-1", {"type": "alert"})
        assert count == 3
        channel, _ = redis_mock.publish.call_args.args
        assert channel == "sphere:org:events:org-1"


class TestPubSubRouterRouting:
    """Unit tests for message routing in PubSubRouter._route_message."""

    @pytest_asyncio.fixture
    async def manager(self):
        mgr = ConnectionManager()
        return mgr

    @pytest_asyncio.fixture
    async def router(self, manager):
        redis = AsyncMock()
        r = PubSubRouter(redis, manager)
        return r

    async def test_route_agent_cmd_calls_send_to_device(self, router, manager):
        ws = AsyncMock()
        await manager.connect(ws, "dev-1", "android", "org-1")

        msg = {"type": "click", "x": 10}
        await router._route_message("sphere:agent:cmd:dev-1", json.dumps(msg))

        ws.send_json.assert_called_once_with(msg)

    async def test_route_org_events_broadcasts(self, router, manager):
        ws1, ws2 = AsyncMock(), AsyncMock()
        await manager.connect(ws1, "dev-1", "android", "org-1")
        await manager.connect(ws2, "dev-2", "android", "org-1")

        event = {"type": "fleet_alert"}
        await router._route_message("sphere:org:events:org-1", json.dumps(event))

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_called_once()

    async def test_route_device_id_with_colon(self, router, manager):
        """Тест MED-7: device_id с двоеточием корректно извлекается через removeprefix."""
        ws = AsyncMock()
        device_id = "192.168.1.1:5555"
        await manager.connect(ws, device_id, "android", "org-1")

        msg = {"type": "command"}
        channel = f"sphere:agent:cmd:{device_id}"
        await router._route_message(channel, json.dumps(msg))

        ws.send_json.assert_called_once_with(msg)
