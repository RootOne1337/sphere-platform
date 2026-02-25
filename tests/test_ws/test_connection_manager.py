# tests/test_ws/test_connection_manager.py
# TZ-03 SPLIT-1: Tests for ConnectionManager in-memory registry.
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest_asyncio

from backend.websocket.connection_manager import ConnectionManager, get_connection_manager


class TestConnectionManager:
    """Unit tests for ConnectionManager (SPLIT-1)."""

    @pytest_asyncio.fixture
    async def manager(self):
        return ConnectionManager()

    @pytest_asyncio.fixture
    async def ws(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        ws.send_bytes = AsyncMock()
        ws.close = AsyncMock()
        return ws

    # ── connect ──────────────────────────────────────────────────────────────

    async def test_connect_returns_session_id(self, manager, ws):
        session_id = await manager.connect(ws, "dev-1", "android", "org-1")
        assert isinstance(session_id, str)
        assert len(session_id) == 32  # hex(16) = 32 chars

    async def test_connect_registers_device(self, manager, ws):
        await manager.connect(ws, "dev-1", "android", "org-1")
        assert manager.is_connected("dev-1")
        assert manager.total_connections == 1

    async def test_connect_multiple_devices(self, manager):
        for i in range(5):
            ws = AsyncMock()
            await manager.connect(ws, f"dev-{i}", "android", "org-1")
        assert manager.total_connections == 5

    async def test_connect_evicts_old_connection(self, manager):
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        await manager.connect(ws1, "dev-1", "android", "org-1")
        await manager.connect(ws2, "dev-1", "android", "org-1")

        # Старое соединение должно было получить close с code 4001
        ws1.close.assert_called_once_with(code=4001, reason="replaced_by_new_connection")
        # Новое соединение активно
        assert manager.is_connected("dev-1")
        assert manager.total_connections == 1

    async def test_connect_builds_org_index(self, manager):
        ws1, ws2 = AsyncMock(), AsyncMock()
        await manager.connect(ws1, "dev-1", "android", "org-1")
        await manager.connect(ws2, "dev-2", "android", "org-1")

        devices = manager.get_connected_devices("org-1")
        assert set(devices) == {"dev-1", "dev-2"}

    # ── disconnect ───────────────────────────────────────────────────────────

    async def test_disconnect_removes_device(self, manager, ws):
        await manager.connect(ws, "dev-1", "android", "org-1")
        info = await manager.disconnect("dev-1")
        assert info is not None
        assert not manager.is_connected("dev-1")
        assert manager.total_connections == 0

    async def test_disconnect_unknown_device_returns_none(self, manager):
        result = await manager.disconnect("nonexistent")
        assert result is None

    async def test_disconnect_cleans_org_index(self, manager):
        ws = AsyncMock()
        await manager.connect(ws, "dev-1", "android", "org-1")
        await manager.disconnect("dev-1")
        assert "dev-1" not in manager.get_connected_devices("org-1")

    # ── send_to_device ───────────────────────────────────────────────────────

    async def test_send_to_device_returns_true_on_success(self, manager, ws):
        await manager.connect(ws, "dev-1", "android", "org-1")
        result = await manager.send_to_device("dev-1", {"type": "ping"})
        assert result is True
        ws.send_json.assert_called_once_with({"type": "ping"})

    async def test_send_to_device_returns_false_if_not_connected(self, manager):
        result = await manager.send_to_device("nonexistent", {"type": "ping"})
        assert result is False

    async def test_send_to_device_disconnects_on_error(self, manager, ws):
        ws.send_json.side_effect = Exception("connection reset")
        await manager.connect(ws, "dev-1", "android", "org-1")

        result = await manager.send_to_device("dev-1", {"type": "ping"})
        assert result is False
        assert not manager.is_connected("dev-1")

    async def test_send_bytes_to_device(self, manager, ws):
        await manager.connect(ws, "dev-1", "android", "org-1")
        result = await manager.send_bytes_to_device("dev-1", b"\x00\x01\x02")
        assert result is True
        ws.send_bytes.assert_called_once_with(b"\x00\x01\x02")

    async def test_send_bytes_returns_false_if_not_connected(self, manager):
        result = await manager.send_bytes_to_device("nonexistent", b"data")
        assert result is False

    # ── broadcast_to_org ─────────────────────────────────────────────────────

    async def test_broadcast_to_org_sends_to_all(self, manager):
        sockets = [AsyncMock() for _ in range(3)]
        for i, ws in enumerate(sockets):
            await manager.connect(ws, f"dev-{i}", "android", "org-1")

        sent_count = await manager.broadcast_to_org("org-1", {"type": "broadcast"})
        assert sent_count == 3
        for ws in sockets:
            ws.send_json.assert_called_once_with({"type": "broadcast"})

    async def test_broadcast_to_org_empty_returns_zero(self, manager):
        count = await manager.broadcast_to_org("empty-org", {"type": "test"})
        assert count == 0

    async def test_broadcast_cross_org_isolation(self, manager):
        ws1, ws2 = AsyncMock(), AsyncMock()
        await manager.connect(ws1, "dev-1", "android", "org-1")
        await manager.connect(ws2, "dev-2", "android", "org-2")

        await manager.broadcast_to_org("org-1", {"type": "org1_event"})

        ws1.send_json.assert_called_once()
        ws2.send_json.assert_not_called()

    # ── singleton ─────────────────────────────────────────────────────────────

    def test_get_connection_manager_singleton(self):
        m1 = get_connection_manager()
        m2 = get_connection_manager()
        assert m1 is m2  # ОДИН синглтон
        assert id(m1) == id(m2)

    # ── misc ─────────────────────────────────────────────────────────────────

    async def test_is_connected_false_for_unknown(self, manager):
        assert not manager.is_connected("unknown")

    async def test_get_connected_devices_empty_org(self, manager):
        assert manager.get_connected_devices("no-such-org") == []

    async def test_total_connections_accurate(self, manager):
        assert manager.total_connections == 0
        for i in range(10):
            ws = AsyncMock()
            await manager.connect(ws, f"d{i}", "android", "org-1")
        assert manager.total_connections == 10
        await manager.disconnect("d0")
        assert manager.total_connections == 9
