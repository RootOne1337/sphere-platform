# tests/vpn/test_health_monitor.py  TZ-06 SPLIT-3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.health_monitor import NoopCommandPublisher, VPNHealthMonitor


def _make_monitor(db_session, pool_service, publisher=None):
    """Helper: create VPNHealthMonitor with mocked HTTP client."""
    if publisher is None:
        publisher = NoopCommandPublisher()
    monitor = VPNHealthMonitor(
        db=db_session,
        pool_service=pool_service,
        publisher=publisher,
        wg_router_url="http://wg-router.test",
    )
    # Mock HTTP client so tests do not need a real WG Router
    monitor._http = MagicMock()
    monitor._http.get = AsyncMock(
        return_value=MagicMock(json=lambda: {}, raise_for_status=lambda: None)
    )
    monitor._http.post = AsyncMock(return_value=MagicMock(status_code=201))
    monitor._http.aclose = AsyncMock()
    return monitor


class TestVPNHealthMonitor:

    @pytest.mark.asyncio
    async def test_check_all_peers_empty_org_returns_zero_stats(
        self, db_session, pool_service, test_org
    ):
        monitor = _make_monitor(db_session, pool_service)
        stats = await monitor.check_all_peers(test_org.id)
        await monitor.close()

        assert stats == {"checked": 0, "stale": 0, "missing": 0, "reconnects": 0}

    @pytest.mark.asyncio
    async def test_fresh_handshake_marks_peer_active(
        self, db_session, pool_service, test_org, test_device, pool_redis
    ):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.device_id == test_device.id)
        )
        peer = result.scalar_one()

        now = datetime.now(timezone.utc)
        handshake_map = {peer.public_key: now - timedelta(seconds=30)}

        monitor = _make_monitor(db_session, pool_service)
        monitor._get_handshake_times = AsyncMock(return_value=handshake_map)
        stats = await monitor.check_all_peers(test_org.id)
        await monitor.close()

        assert stats["checked"] == 1
        assert stats["stale"] == 0
        assert peer.is_active is True

    @pytest.mark.asyncio
    async def test_stale_handshake_marks_peer_inactive(
        self, db_session, pool_service, test_org, test_device, pool_redis
    ):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.device_id == test_device.id)
        )
        peer = result.scalar_one()

        stale_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        handshake_map = {peer.public_key: stale_time}

        publisher = NoopCommandPublisher()
        monitor = _make_monitor(db_session, pool_service, publisher=publisher)
        monitor._get_handshake_times = AsyncMock(return_value=handshake_map)
        # Device offline -- no reconnect
        monitor._is_device_online = AsyncMock(return_value=False)
        stats = await monitor.check_all_peers(test_org.id)
        await monitor.close()

        assert stats["stale"] == 1
        assert stats["reconnects"] == 0
        assert peer.is_active is False

    @pytest.mark.asyncio
    async def test_stale_handshake_triggers_reconnect_for_online_device(
        self, db_session, pool_service, test_org, test_device, pool_redis
    ):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.device_id == test_device.id)
        )
        peer = result.scalar_one()

        stale_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        handshake_map = {peer.public_key: stale_time}

        publisher = MagicMock()
        publisher.send_command_to_device = AsyncMock(return_value=True)
        publisher.is_device_online = AsyncMock(return_value=True)

        monitor = _make_monitor(db_session, pool_service, publisher=publisher)
        monitor._get_handshake_times = AsyncMock(return_value=handshake_map)
        monitor._is_device_online = AsyncMock(return_value=True)
        stats = await monitor.check_all_peers(test_org.id)
        await monitor.close()

        assert stats["reconnects"] == 1
        publisher.send_command_to_device.assert_called_once()
        cmd = publisher.send_command_to_device.call_args[0][1]
        assert cmd["type"] == "vpn_reconnect"
        assert cmd["reason"] == "stale_handshake"

    @pytest.mark.asyncio
    async def test_missing_peer_triggers_readd_to_wg_server(
        self, db_session, pool_service, test_org, test_device, pool_redis
    ):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        monitor = _make_monitor(db_session, pool_service)
        monitor._get_handshake_times = AsyncMock(return_value={})
        stats = await monitor.check_all_peers(test_org.id)
        await monitor.close()

        assert stats["missing"] == 1
        pool_service._add_peer_to_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_handshake_fetch_failure_returns_empty(
        self, db_session, pool_service, test_org
    ):
        monitor = _make_monitor(db_session, pool_service)
        monitor._http.get.side_effect = Exception("Connection refused")
        times = await monitor._get_handshake_times()
        await monitor.close()

        assert times == {}

    @pytest.mark.asyncio
    async def test_close_calls_http_aclose(
        self, db_session, pool_service
    ):
        monitor = _make_monitor(db_session, pool_service)
        await monitor.close()
        monitor._http.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_all_peers_returns_correct_keys(
        self, db_session, pool_service, test_org, test_device, pool_redis
    ):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        monitor = _make_monitor(db_session, pool_service)
        monitor._get_handshake_times = AsyncMock(return_value={})
        stats = await monitor.check_all_peers(test_org.id)
        await monitor.close()

        assert set(stats.keys()) == {"checked", "stale", "missing", "reconnects"}
        assert stats["checked"] == 1

    @pytest.mark.asyncio
    async def test_is_device_online_no_redis_returns_true(
        self, db_session, pool_service
    ):
        monitor = _make_monitor(db_session, pool_service)
        result = await monitor._is_device_online("any-device-id")
        await monitor.close()
        assert result is True
