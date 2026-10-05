"""Pool counts use isolated SQL; no router or Android commands are issued."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from backend.models import Device, Organization
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("age_seconds,active_flag,state,bound,expected_active,expected_stale", [
    (0, True, VPNPeerStatus.ASSIGNED, True, 1, 0),
    (179, True, VPNPeerStatus.ASSIGNED, True, 1, 0),
    (180, True, VPNPeerStatus.ASSIGNED, True, 0, 1),
    (600, True, VPNPeerStatus.ASSIGNED, True, 0, 1),
    (None, True, VPNPeerStatus.ASSIGNED, True, 0, 0),
    (-1, True, VPNPeerStatus.ASSIGNED, True, 0, 0),
    (10, False, VPNPeerStatus.ASSIGNED, True, 0, 0),
    (10, True, VPNPeerStatus.FREE, False, 0, 0),
    (10, True, VPNPeerStatus.PROVISIONING, True, 0, 0),
    (10, True, VPNPeerStatus.REVOKING, True, 0, 0),
    (10, True, VPNPeerStatus.ERROR, True, 0, 0),
    (10, True, VPNPeerStatus.ASSIGNED, False, 0, 0),
])
async def test_active_pool_count_expires_without_another_health_poll(
    vpn_admin_client, db_session, test_org, test_device,
    age_seconds, active_flag, state, bound, expected_active, expected_stale,
):
    db_session.add(VPNPeer(
        org_id=test_org.id,
        device_id=test_device.id if bound else None,
        public_key="isolated-count-fixture",
        private_key_enc=b"not-used-by-read",
        status=state,
        is_active=active_flag,
        last_handshake_at=None if age_seconds is None else NOW - timedelta(seconds=age_seconds),
    ))
    await db_session.flush()
    with patch("backend.api.v1.vpn.router.datetime") as clock:
        clock.now.return_value = NOW
        response = await vpn_admin_client.get("/api/v1/vpn/pool/stats")
        peers = await vpn_admin_client.get("/api/v1/vpn/peers")
    assert response.status_code == 200
    result = response.json()
    assert result["active_tunnels"] == expected_active
    assert result["stale_handshakes"] == expected_stale
    assert result["allocated"] == (0 if state == VPNPeerStatus.FREE else 1)
    assert datetime.fromisoformat(result["observed_at"]) == NOW
    assert result["handshake_max_age_seconds"] == 180
    assert peers.status_code == 200
    assert len(peers.json()) == 1
    assert peers.json()[0]["is_active"] is bool(expected_active)


async def test_pool_observations_exclude_foreign_organization(
    vpn_admin_client, db_session,
):
    foreign_org = Organization(name="Isolated foreign count", slug="isolated-foreign-count")
    db_session.add(foreign_org)
    await db_session.flush()
    foreign_device = Device(org_id=foreign_org.id, name="Isolated foreign device")
    db_session.add(foreign_device)
    await db_session.flush()
    db_session.add(VPNPeer(
        org_id=foreign_org.id, device_id=foreign_device.id,
        public_key="isolated-foreign-count-fixture",
        private_key_enc=b"not-used-by-read", status=VPNPeerStatus.ASSIGNED,
        is_active=True, last_handshake_at=NOW,
    ))
    await db_session.flush()
    with patch("backend.api.v1.vpn.router.datetime") as clock:
        clock.now.return_value = NOW
        response = await vpn_admin_client.get("/api/v1/vpn/pool/stats")
    assert response.status_code == 200
    assert response.json()["active_tunnels"] == 0
    assert response.json()["stale_handshakes"] == 0
    assert response.json()["allocated"] == 0
