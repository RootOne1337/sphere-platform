"""Real PostgreSQL peers; in-memory router transport, no external VPN calls."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.health_monitor import VPNHealthMonitor
from backend.services.vpn.pool_service import VPNPoolService
from backend.tasks.vpn_health import _run_health_checks


@pytest_asyncio.fixture
async def health_world(world):
    cipher = Fernet(Fernet.generate_key())
    observed_at = datetime.now(timezone.utc) - timedelta(seconds=300)
    async with world.sessions() as db:
        peer = VPNPeer(
            org_id=world.org_a.id, device_id=world.dev_a.id,
            public_key="audit-peer-public-key", tunnel_ip="10.210.0.2",
            private_key_enc=cipher.encrypt(b"audit-private-key"),
            preshared_key_enc=cipher.encrypt(b"audit-preshared-key"),
            status=VPNPeerStatus.ASSIGNED, is_active=True,
            last_handshake_at=observed_at,
            awg_jc=4, awg_jmin=0, awg_jmax=100, awg_s1=10, awg_s2=20,
            awg_h1=101, awg_h2=102, awg_h3=103, awg_h4=104,
        )
        db.add(peer)
        await db.commit()
        service = VPNPoolService(
            db, AsyncMock(), AWGConfigBuilder("audit-server-key", "127.0.0.1:9"),
            cipher, "http://127.0.0.1:9", wg_router_api_key="audit-router-key",
        )
        monitors = []
        requests = []
        publisher = SimpleNamespace(send_command_to_device=AsyncMock(return_value=True))
        client_type = httpx.AsyncClient

        def make_monitor(response):
            def handle(request):
                requests.append(request)
                if isinstance(response, Exception):
                    raise response
                return response

            def client(**kwargs):
                return client_type(transport=httpx.MockTransport(handle), **kwargs)

            with patch("backend.services.vpn.health_monitor.httpx.AsyncClient", side_effect=client):
                monitor = VPNHealthMonitor(db, service, publisher, "http://127.0.0.1:9")
            monitors.append(monitor)
            return monitor

        try:
            yield SimpleNamespace(**locals())
        finally:
            for monitor in monitors:
                await monitor.close()
            await service.close()


@pytest.mark.parametrize("failure", [
    "timeout", "unauthorized", "unavailable", "bad_json", "list", "string_timestamp",
    "negative_timestamp", "bool_timestamp", "overflow_timestamp",
    "nan_timestamp", "future_timestamp",
])
async def test_untrusted_router_snapshot_preserves_peers_without_mutation(health_world, failure):
    h = health_world
    responses = {
        "timeout": httpx.ReadTimeout("audit lost response"),
        "unauthorized": httpx.Response(401, json={}),
        "unavailable": httpx.Response(503, json={}),
        "bad_json": httpx.Response(200, text="not json"),
        "list": httpx.Response(200, json=[]),
        "string_timestamp": httpx.Response(200, json={h.peer.public_key: "yesterday"}),
        "negative_timestamp": httpx.Response(200, json={h.peer.public_key: -1}),
        "bool_timestamp": httpx.Response(200, json={h.peer.public_key: True}),
        "overflow_timestamp": httpx.Response(200, json={h.peer.public_key: 10**20}),
        "nan_timestamp": httpx.Response(200, text='{"audit-peer-public-key": NaN}'),
        "future_timestamp": httpx.Response(200, json={
            h.peer.public_key: (datetime.now(timezone.utc) + timedelta(days=1)).timestamp(),
        }),
    }
    monitor = h.make_monitor(responses[failure])
    stats = await monitor.check_all_peers(h.world.org_a.id)
    await h.db.commit()
    async with h.world.sessions() as verify:
        peer = await verify.get(VPNPeer, h.peer.id)
        assert peer.is_active is True
        assert peer.last_handshake_at == h.observed_at
        assert peer.status == VPNPeerStatus.ASSIGNED
    assert [request.method for request in h.requests] == ["GET"], "Poll failure must not recreate peers"
    assert stats["checked"] == 0, "Unknown router state must not be reported as a completed check"
    h.publisher.send_command_to_device.assert_not_awaited()


@pytest.mark.parametrize("snapshot", ["missing", "never_handshaken"])
async def test_no_handshake_does_not_prove_router_peer_is_absent(health_world, snapshot):
    h = health_world
    payload = {} if snapshot == "missing" else {h.peer.public_key: 0}
    monitor = h.make_monitor(httpx.Response(200, json=payload))
    stats = await monitor.check_all_peers(h.world.org_a.id)
    await h.db.commit()
    assert [request.method for request in h.requests] == ["GET"], "Handshake API is not a peer inventory"
    assert stats["missing"] == 1
    assert h.peer.is_active is False
    h.publisher.send_command_to_device.assert_not_awaited()


async def test_health_poll_uses_configured_router_authentication(health_world):
    h = health_world
    monitor = h.make_monitor(httpx.Response(200, json={h.peer.public_key: h.observed_at.timestamp()}))
    await monitor._get_handshake_times()
    assert h.requests[0].headers.get("X-API-Key") == "audit-router-key"


async def test_reconnect_preserves_assigned_psk_and_obfuscation(health_world):
    h = health_world
    expected = await h.service._peer_to_assignment(h.peer)
    monitor = h.make_monitor(httpx.Response(200, json={h.peer.public_key: h.observed_at.timestamp()}))
    monitor._is_device_online = AsyncMock(return_value=True)
    stats = await monitor.check_all_peers(h.world.org_a.id)
    assert stats["reconnects"] == 1
    command = h.publisher.send_command_to_device.call_args.args[1]
    assert command["config"] == expected.config, "Recovery must retain the original tunnel credentials"


async def test_health_check_recovers_on_next_successful_poll(health_world):
    h = health_world
    monitor = h.make_monitor(httpx.Response(503, json={}))
    failed = await monitor.check_all_peers(h.world.org_a.id)
    assert failed["checked"] == 0
    recovered = h.make_monitor(httpx.Response(200, json={
        h.peer.public_key: datetime.now(timezone.utc).timestamp(),
    }))
    stats = await recovered.check_all_peers(h.world.org_a.id)
    await h.db.commit()
    assert stats == {"checked": 1, "stale": 0, "missing": 0, "reconnects": 0}
    assert h.peer.is_active is True
    assert h.peer.last_handshake_at > h.observed_at
    h.publisher.send_command_to_device.assert_not_awaited()


@pytest.mark.parametrize("age_seconds", [10, 600])
async def test_revoked_peer_is_not_reactivated_or_reconnected_by_inflight_poll(health_world, age_seconds):
    h = health_world
    monitor = h.make_monitor(httpx.Response(200, json={}))
    monitor._is_device_online = AsyncMock(return_value=True)

    async def revoke_during_poll():
        async with h.world.sessions() as revoke_db:
            peer = await revoke_db.get(VPNPeer, h.peer.id)
            peer.status = VPNPeerStatus.FREE
            peer.device_id = None
            peer.is_active = False
            await revoke_db.commit()
        return {h.peer.public_key: datetime.now(timezone.utc) - timedelta(seconds=age_seconds)}

    monitor._get_handshake_times = revoke_during_poll
    stats = await monitor.check_all_peers(h.world.org_a.id)
    await h.db.commit()
    async with h.world.sessions() as verify:
        peer = await verify.get(VPNPeer, h.peer.id)
        assert peer.status == VPNPeerStatus.FREE
        assert peer.device_id is None
        assert peer.is_active is False
    h.publisher.send_command_to_device.assert_not_awaited()
    assert stats["checked"] == 0


@pytest.mark.parametrize("snapshot", ["stale", "missing"])
async def test_late_health_response_cannot_overwrite_a_newer_observation(health_world, snapshot):
    h = health_world
    monitor = h.make_monitor(httpx.Response(200, json={}))
    monitor._is_device_online = AsyncMock(return_value=True)
    fresh = datetime.now(timezone.utc)

    async def newer_cycle_finishes_first():
        async with h.world.sessions() as other_db:
            peer = await other_db.get(VPNPeer, h.peer.id)
            peer.last_handshake_at = fresh
            peer.is_active = True
            await other_db.commit()
        return {h.peer.public_key: h.observed_at} if snapshot == "stale" else {}

    monitor._get_handshake_times = newer_cycle_finishes_first
    await monitor.check_all_peers(h.world.org_a.id)
    await h.db.commit()
    async with h.world.sessions() as verify:
        peer = await verify.get(VPNPeer, h.peer.id)
        assert peer.last_handshake_at == fresh
        assert peer.is_active is True
    h.publisher.send_command_to_device.assert_not_awaited()


@pytest.mark.parametrize("fail_first_commit", [False, True])
async def test_background_health_cycle_commits_observations_and_authenticates(health_world, fail_first_commit):
    h = health_world
    from sqlalchemy import case

    from backend.models.organization import Organization

    other_peer = VPNPeer(
        org_id=h.world.org_b.id, device_id=h.world.dev_b.id,
        public_key="audit-other-peer-key", tunnel_ip="10.210.0.3",
        private_key_enc=h.cipher.encrypt(b"audit-other-private-key"),
        status=VPNPeerStatus.ASSIGNED, is_active=False, last_handshake_at=h.observed_at,
    )
    h.db.add(other_peer)
    await h.db.commit()
    contexts = []

    @asynccontextmanager
    async def scoped_session(org_id=None):
        # Scope only organization enumeration to this disposable fixture. Peer
        # reads/writes and commit/close behavior use the real PostgreSQL session.
        async with h.world.sessions() as db:
            execute = db.execute

            async def execute_scoped(statement, *args, **kwargs):
                if any(desc.get("entity") is Organization for desc in statement.column_descriptions):
                    statement = statement.where(Organization.id.in_([
                        h.world.org_a.id, h.world.org_b.id,
                    ])).order_by(case((Organization.id == h.world.org_a.id, 0), else_=1))
                return await execute(statement, *args, **kwargs)

            db.execute = execute_scoped
            if org_id:
                contexts.append(org_id)
            if fail_first_commit and org_id == str(h.world.org_a.id):
                db.commit = AsyncMock(side_effect=ConnectionError("audit commit failed"))
            yield db

    requests = []
    fresh = datetime.now(timezone.utc)
    client_type = httpx.AsyncClient

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={
            h.peer.public_key: fresh.timestamp(), other_peer.public_key: fresh.timestamp(),
        })

    def client(**kwargs):
        return client_type(transport=httpx.MockTransport(handle), **kwargs)

    with (
        patch("backend.database.engine.get_db_session", scoped_session),
        patch("backend.database.redis_client.redis", h.world.redis),
        patch("backend.services.vpn.dependencies.get_awg_config_builder", return_value=h.service.config_builder),
        patch("backend.services.vpn.dependencies.get_key_cipher", return_value=h.cipher),
        patch("backend.core.config.settings.WG_ROUTER_API_KEY", "audit-router-key"),
        patch("backend.services.vpn.health_monitor.httpx.AsyncClient", side_effect=client),
    ):
        await _run_health_checks()
    async with h.world.sessions() as verify:
        peer = await verify.get(VPNPeer, h.peer.id)
        expected = h.observed_at if fail_first_commit else fresh
        assert peer.last_handshake_at == expected, "Only a committed observation may survive session close"
        assert peer.is_active is True
        second = await verify.get(VPNPeer, other_peer.id)
        assert second.last_handshake_at == fresh, "One tenant's failed commit must not stop the next tenant"
        assert second.is_active is True
    assert contexts == [str(h.world.org_a.id), str(h.world.org_b.id)]
    assert [request.method for request in requests] == ["GET", "GET"]
    assert all(request.headers.get("X-API-Key") == "audit-router-key" for request in requests)
