# tests/test_ws/test_startup.py
# Tests for backend/websocket/startup.py — WS component initialization hook.
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestStartupWsComponents:

    @pytest.mark.asyncio
    async def test_startup_initializes_all_components(self):
        """_startup_ws_components wires together all WS singletons."""
        from backend.websocket.startup import _startup_ws_components

        mock_manager = MagicMock()
        mock_bridge = MagicMock()
        mock_pubsub_pub = MagicMock()
        mock_events_mgr = MagicMock()

        with (
            patch("backend.websocket.connection_manager.get_connection_manager",
                  return_value=mock_manager) as _get_mgr,
            patch("backend.websocket.stream_bridge.init_stream_bridge",
                  return_value=mock_bridge) as _init_bridge,
            patch("backend.websocket.pubsub_router.get_pubsub_publisher",
                  return_value=mock_pubsub_pub) as _get_pub,
            patch("backend.api.ws.events.router.get_events_manager",
                  return_value=mock_events_mgr) as _get_ev,
            patch("backend.websocket.event_publisher.init_event_publisher") as mock_init_ep,
        ):
            await _startup_ws_components()

            _get_mgr.assert_called_once()
            _init_bridge.assert_called_once_with(mock_manager)
            _get_pub.assert_called_once()
            _get_ev.assert_called_once()
            mock_init_ep.assert_called_once_with(mock_pubsub_pub, mock_events_mgr)
