# tests/test_ws/test_stream_bridge.py
# Tests for VideoStreamBridge — Android agent → browser viewer relay.
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.websocket.stream_bridge import (
    VideoStreamBridge,
    get_stream_bridge,
    init_stream_bridge,
)


@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.send_to_device = AsyncMock()
    return manager


@pytest.fixture
def bridge(mock_manager):
    return VideoStreamBridge(mock_manager)


class TestVideoStreamBridgeInit:

    def test_init_creates_empty_state(self, mock_manager):
        b = VideoStreamBridge(mock_manager)
        assert b.manager is mock_manager
        assert b._queues == {}
        assert b._viewer_sockets == {}
        assert b._viewer_tasks == {}

    def test_is_streaming_initially_false(self, bridge):
        assert bridge.is_streaming("device-1") is False

    def test_get_drop_ratio_no_queue(self, bridge):
        assert bridge.get_drop_ratio("device-1") == 0.0


class TestHandleAgentFrame:

    @pytest.mark.asyncio
    async def test_handle_frame_no_viewer_is_noop(self, bridge):
        # No queue registered — silently drop frame
        await bridge.handle_agent_frame("device-1", b"\x00\xAA\xBB\xCC")
        # No exception raised

    @pytest.mark.asyncio
    async def test_handle_frame_with_viewer_puts_in_queue(self, bridge, mock_manager):
        device_id = "device-stream-1"
        viewer_ws = AsyncMock()
        viewer_ws.send_bytes = AsyncMock()

        # Register viewer to create the queue
        task = asyncio.get_event_loop().create_task(
            bridge.register_viewer(device_id, viewer_ws, "sess-1")
        )
        await task

        # Now send a frame — it should go into the queue
        await bridge.handle_agent_frame(device_id, b"\x00\x01\x02\x03")
        assert bridge.is_streaming(device_id)

        # Cleanup
        await bridge.unregister_viewer(device_id)


class TestInitStreamBridge:

    def test_init_sets_singleton(self, mock_manager):
        bridge = init_stream_bridge(mock_manager)
        assert bridge is not None
        assert isinstance(bridge, VideoStreamBridge)

    def test_get_stream_bridge_returns_set_instance(self, mock_manager):
        bridge = init_stream_bridge(mock_manager)
        assert get_stream_bridge() is bridge

    def test_init_replaces_existing_singleton(self, mock_manager):
        bridge1 = init_stream_bridge(mock_manager)
        bridge2 = init_stream_bridge(mock_manager)
        assert bridge2 is not bridge1
        assert get_stream_bridge() is bridge2


class TestRegisterUnregisterViewer:

    @pytest.mark.asyncio
    async def test_register_viewer_marks_streaming(self, bridge, mock_manager):
        device_id = "device-reg-1"
        viewer_ws = AsyncMock()

        await bridge.register_viewer(device_id, viewer_ws, "sess-1")
        assert bridge.is_streaming(device_id)

        # Cleanup background task
        task = bridge._viewer_tasks.get(device_id)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_register_viewer_signals_agent_to_start(self, bridge, mock_manager):
        device_id = "device-reg-2"
        viewer_ws = AsyncMock()

        await bridge.register_viewer(device_id, viewer_ws, "sess-2")

        mock_manager.send_to_device.assert_called_with(device_id, {
            "type": "start_stream",
            "quality": "720p",
            "bitrate": 2_000_000,
        })

        task = bridge._viewer_tasks.get(device_id)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    @pytest.mark.asyncio
    async def test_unregister_viewer_clears_state(self, bridge, mock_manager):
        device_id = "device-unreg-1"
        viewer_ws = AsyncMock()

        await bridge.register_viewer(device_id, viewer_ws, "sess-3")
        await bridge.unregister_viewer(device_id)

        assert bridge.is_streaming(device_id) is False
        assert device_id not in bridge._viewer_sockets
        assert device_id not in bridge._queues

    @pytest.mark.asyncio
    async def test_get_drop_ratio_with_queue(self, bridge, mock_manager):
        device_id = "device-drop-1"
        viewer_ws = AsyncMock()

        await bridge.register_viewer(device_id, viewer_ws, "sess-4")
        # Fresh queue — no drops
        ratio = bridge.get_drop_ratio(device_id)
        assert ratio == 0.0

        task = bridge._viewer_tasks.get(device_id)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
