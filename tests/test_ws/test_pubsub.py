# tests/test_ws/test_pubsub.py
# TZ-03 SPLIT-2: Tests for PubSubPublisher, PubSubRouter, and ChannelPattern.
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
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

    async def test_send_command_to_device_queued_when_no_subscribers(
        self, publisher, redis_mock
    ):
        """When no subscribers, command is queued (offline queue returns True)."""
        redis_mock.publish.return_value = 0
        # Without offline queue singleton, result depends on queue availability
        # In test env, offline queue is not initialized → returns False
        result = await publisher.send_command_to_device("dev-1", {"type": "click"})
        assert result is False  # no offline queue in test env

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

    async def test_send_command_inner_delivered(self, publisher, redis_mock):
        """_send_command_inner returns (True, False) when delivered to online device."""
        redis_mock.publish.return_value = 1
        success, queued = await publisher._send_command_inner("dev-1", {"type": "tap"})
        assert success is True
        assert queued is False

    async def test_send_command_inner_offline_no_queue(self, publisher, redis_mock):
        """_send_command_inner returns (False, False) when offline and no queue."""
        redis_mock.publish.return_value = 0
        success, queued = await publisher._send_command_inner("dev-1", {"type": "tap"})
        assert success is False
        assert queued is False


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

    async def test_route_video_stream_channel(self, router):
        """Video stream channel routes frame to stream bridge."""
        from unittest.mock import AsyncMock as _AM
        from unittest.mock import patch

        bridge_mock = _AM()
        bridge_mock.handle_agent_frame = _AM()

        with patch("backend.websocket.stream_bridge.get_stream_bridge", return_value=bridge_mock):
            await router._route_message(
                "sphere:stream:video:device-1",
                b"\x00\xFF\x00\xFF",
            )
            bridge_mock.handle_agent_frame.assert_called_once_with("device-1", b"\x00\xFF\x00\xFF")

    async def test_route_video_no_bridge_is_noop(self, router):
        """When no stream bridge, video route should not raise."""
        from unittest.mock import patch

        with patch("backend.websocket.stream_bridge.get_stream_bridge", return_value=None):
            await router._route_message("sphere:stream:video:device-2", b"\xAA")
            # No exception

    async def test_forward_video_exceptions_are_swallowed(self, router):
        """_forward_video_to_viewers catches and logs exceptions."""
        from unittest.mock import AsyncMock as _AM
        from unittest.mock import patch

        failing_bridge = _AM()
        failing_bridge.handle_agent_frame = _AM(side_effect=Exception("test error"))

        with patch("backend.websocket.stream_bridge.get_stream_bridge", return_value=failing_bridge):
            # Should NOT raise
            await router._forward_video_to_viewers("dev-1", b"\x00")


class TestPubSubRouterLifecycle:
    """Unit tests for PubSubRouter start/stop/subscribe/unsubscribe."""

    @pytest_asyncio.fixture
    async def mock_redis(self):
        from unittest.mock import MagicMock
        redis = AsyncMock()
        pubsub = AsyncMock()
        pubsub.subscribe = AsyncMock()
        pubsub.unsubscribe = AsyncMock()
        pubsub.aclose = AsyncMock()
        pubsub.subscribed = False
        # pubsub() is a synchronous call that returns a pubsub object
        redis.pubsub = MagicMock(return_value=pubsub)
        return redis, pubsub

    async def test_subscribe_device_no_pubsub_is_noop(self, mock_redis):
        redis, _ = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)
        # _pubsub is None initially — should return without raising
        await router.subscribe_device("dev-1", "org-1")

    async def test_unsubscribe_device_no_pubsub_is_noop(self, mock_redis):
        redis, _ = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)
        await router.unsubscribe_device("dev-1")

    async def test_subscribe_device_subscribes_channels(self, mock_redis):
        redis, pubsub_mock = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)
        router._pubsub = pubsub_mock

        await router.subscribe_device("dev-1", "org-1")

        calls = [c.args[0] for c in pubsub_mock.subscribe.call_args_list]
        assert "sphere:agent:cmd:dev-1" in calls
        assert "sphere:org:events:org-1" in calls

    async def test_subscribe_device_deduplicates_channels(self, mock_redis):
        redis, pubsub_mock = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)
        router._pubsub = pubsub_mock

        await router.subscribe_device("dev-1", "org-1")
        await router.subscribe_device("dev-2", "org-1")  # same org — should not re-subscribe

        org_subs = [
            c for c in pubsub_mock.subscribe.call_args_list
            if c.args[0] == "sphere:org:events:org-1"
        ]
        assert len(org_subs) == 1  # only subscribed once

    async def test_unsubscribe_device_removes_channel(self, mock_redis):
        redis, pubsub_mock = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)
        router._pubsub = pubsub_mock
        router._subscribed_channels.add("sphere:agent:cmd:dev-1")

        await router.unsubscribe_device("dev-1")

        pubsub_mock.unsubscribe.assert_called_once_with("sphere:agent:cmd:dev-1")
        assert "sphere:agent:cmd:dev-1" not in router._subscribed_channels

    async def test_start_creates_pubsub_and_task(self, mock_redis):
        import asyncio as _asyncio
        redis, pubsub_mock = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)

        await router.start()
        assert router._pubsub is pubsub_mock
        assert router._task is not None

        # Cleanup background task
        router._task.cancel()
        try:
            await router._task
        except (_asyncio.CancelledError, Exception):
            pass

    async def test_stop_cancels_task(self, mock_redis):
        redis, pubsub_mock = mock_redis
        manager = ConnectionManager()
        router = PubSubRouter(redis, manager)
        await router.start()

        task = router._task
        await router.stop()

        assert task.cancelled() or task.done()
        pubsub_mock.aclose.assert_called_once()


class TestPubSubModuleHooks:
    """Tests for _startup_pubsub and _shutdown_pubsub module-level hooks."""

    @pytest.mark.asyncio
    async def test_startup_pubsub_no_redis_logs_warning(self, caplog):
        """If redis is None, _startup_pubsub logs a warning and returns early."""
        import logging
        from unittest.mock import patch

        import backend.websocket.pubsub_router as _mod

        with patch("backend.database.redis_client.redis", None), \
             patch.object(_mod, "_pubsub_router_instance", None), \
             patch.object(_mod, "_pubsub_publisher_instance", None):
            with caplog.at_level(logging.WARNING, logger="backend.websocket.pubsub_router"):
                await _mod._startup_pubsub()
            assert "Redis not available" in caplog.text
            assert _mod._pubsub_router_instance is None

    @pytest.mark.asyncio
    async def test_startup_pubsub_with_redis_creates_instances(self):
        """If redis is available, _startup_pubsub creates router and publisher."""
        from unittest.mock import AsyncMock, MagicMock, patch

        import backend.websocket.pubsub_router as _mod

        fake_redis = AsyncMock()
        fake_pubsub = AsyncMock()
        fake_pubsub.subscribe = AsyncMock()
        fake_redis.pubsub = MagicMock(return_value=fake_pubsub)

        fake_router = AsyncMock()
        fake_router.start = AsyncMock()

        with patch("backend.database.redis_client.redis", fake_redis), \
             patch.object(_mod, "_pubsub_router_instance", None), \
             patch.object(_mod, "_pubsub_publisher_instance", None), \
             patch("backend.websocket.pubsub_router.PubSubPublisher") as MockPublisher, \
             patch("backend.websocket.pubsub_router.PubSubRouter") as MockRouter, \
             patch("backend.websocket.pubsub_router.get_connection_manager"):
            MockRouter.return_value = fake_router
            await _mod._startup_pubsub()
            MockPublisher.assert_called_once_with(fake_redis)
            MockRouter.assert_called_once()
            fake_router.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_pubsub_when_router_exists(self):
        """_shutdown_pubsub stops and clears _pubsub_router_instance."""
        from unittest.mock import AsyncMock, patch

        import backend.websocket.pubsub_router as _mod

        fake_router = AsyncMock()
        fake_router.stop = AsyncMock()

        with patch.object(_mod, "_pubsub_router_instance", fake_router):
            await _mod._shutdown_pubsub()
            fake_router.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_pubsub_when_no_router(self):
        """_shutdown_pubsub is a no-op when _pubsub_router_instance is None."""
        from unittest.mock import patch

        import backend.websocket.pubsub_router as _mod

        with patch.object(_mod, "_pubsub_router_instance", None):
            await _mod._shutdown_pubsub()  # should not raise

    def test_get_pubsub_router_returns_instance(self):
        """get_pubsub_router reflects the current module-level instance."""
        from unittest.mock import patch

        import backend.websocket.pubsub_router as _mod
        from backend.websocket.pubsub_router import get_pubsub_router

        sentinel = object()
        with patch.object(_mod, "_pubsub_router_instance", sentinel):
            assert get_pubsub_router() is sentinel

    def test_get_pubsub_publisher_returns_instance(self):
        """get_pubsub_publisher reflects the current module-level instance."""
        from unittest.mock import patch

        import backend.websocket.pubsub_router as _mod
        from backend.websocket.pubsub_router import get_pubsub_publisher

        sentinel = object()
        with patch.object(_mod, "_pubsub_publisher_instance", sentinel):
            assert get_pubsub_publisher() is sentinel

