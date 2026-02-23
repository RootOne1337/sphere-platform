# tests/vpn/test_vpn_api.py  TZ-06 SPLIT-5
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.pool_service import VPNAssignment


class TestVPNAssignEndpoint:

    @pytest.mark.asyncio
    async def test_assign_returns_200_with_config(
        self, vpn_admin_client, test_device, test_org, pool_redis
    ):
        mock_assignment = VPNAssignment(
            peer_id=str(uuid.uuid4()),
            device_id=str(test_device.id),
            assigned_ip="10.100.0.1",
            config="[Interface]\nPrivateKey = test\n",
            qr_code="iVBORw==",
            public_key="dGVzdHB1YmxpY2tleT09",
        )

        with patch(
            "backend.services.vpn.pool_service.VPNPoolService.assign_vpn",
            new_callable=AsyncMock,
            return_value=mock_assignment,
        ):
            resp = await vpn_admin_client.post(
                "/api/v1/vpn/assign",
                json={"device_id": str(test_device.id), "split_tunnel": True},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["assigned_ip"] == "10.100.0.1"
        assert "config" in data
        assert "qr_code" in data

    @pytest.mark.asyncio
    async def test_assign_requires_org_admin(self, vpn_manager_client, test_device):
        resp = await vpn_manager_client.post(
            "/api/v1/vpn/assign",
            json={"device_id": str(test_device.id)},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_assign_unauthenticated_returns_401(self, test_device):
        from httpx import ASGITransport, AsyncClient

        from backend.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            resp = await client.post(
                "/api/v1/vpn/assign",
                json={"device_id": str(test_device.id)},
            )
        assert resp.status_code == 401


class TestVPNRevokeEndpoint:

    @pytest.mark.asyncio
    async def test_revoke_returns_204(
        self, vpn_admin_client, test_device
    ):
        with patch(
            "backend.services.vpn.pool_service.VPNPoolService.revoke_vpn",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await vpn_admin_client.delete(
                f"/api/v1/vpn/revoke/{test_device.id}"
            )
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_revoke_requires_org_admin(self, vpn_manager_client, test_device):
        resp = await vpn_manager_client.delete(
            f"/api/v1/vpn/revoke/{test_device.id}"
        )
        assert resp.status_code == 403


class TestVPNPeersEndpoint:

    @pytest.mark.asyncio
    async def test_list_peers_returns_200(
        self, vpn_admin_client, db_session, test_org, test_device
    ):
        # Create a peer in DB
        from cryptography.fernet import Fernet
        cipher = Fernet(Fernet.generate_key())
        peer = VPNPeer(
            org_id=test_org.id,
            device_id=test_device.id,
            public_key="dGVzdF9wdWJsaWNfa2V5XzQ0Y2hhcl9iYXNlNjQ=",
            private_key_enc=cipher.encrypt(b"test-private-key"),
            tunnel_ip="10.100.0.5",
            status=VPNPeerStatus.ASSIGNED,
        )
        db_session.add(peer)
        await db_session.flush()

        resp = await vpn_admin_client.get("/api/v1/vpn/peers")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["assigned_ip"] == "10.100.0.5"
        assert data[0]["status"] == "assigned"

    @pytest.mark.asyncio
    async def test_list_peers_filter_by_status(
        self, vpn_admin_client, db_session, test_org, test_device
    ):
        from cryptography.fernet import Fernet
        cipher = Fernet(Fernet.generate_key())
        peer = VPNPeer(
            org_id=test_org.id,
            device_id=test_device.id,
            public_key="dGVzdF9wdWJsaWNfa2V5XzQ0Y2hhcl9iYXNlNjQ=",
            private_key_enc=cipher.encrypt(b"test-private-key"),
            tunnel_ip="10.100.0.5",
            status=VPNPeerStatus.ASSIGNED,
        )
        db_session.add(peer)
        await db_session.flush()

        resp = await vpn_admin_client.get("/api/v1/vpn/peers?status=assigned")
        assert resp.status_code == 200
        assert all(p["status"] == "assigned" for p in resp.json())

    @pytest.mark.asyncio
    async def test_list_peers_accessible_to_device_manager(
        self, vpn_manager_client
    ):
        resp = await vpn_manager_client.get("/api/v1/vpn/peers")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_list_peers_invalid_status_returns_422(self, vpn_admin_client):
        resp = await vpn_admin_client.get("/api/v1/vpn/peers?status=invalid")
        assert resp.status_code == 422


class TestVPNPoolStatsEndpoint:

    @pytest.mark.asyncio
    async def test_pool_stats_returns_structure(self, vpn_admin_client):
        resp = await vpn_admin_client.get("/api/v1/vpn/pool/stats")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("total_ips", "allocated", "free", "active_tunnels", "stale_handshakes"):
            assert field in data
            assert isinstance(data[field], int)

    @pytest.mark.asyncio
    async def test_pool_stats_accessible_to_manager(self, vpn_manager_client):
        resp = await vpn_manager_client.get("/api/v1/vpn/pool/stats")
        assert resp.status_code == 200


class TestKillSwitchEndpoint:

    @pytest.mark.asyncio
    async def test_enable_killswitch_returns_results(self, vpn_admin_client):
        dev1 = str(uuid.uuid4())
        dev2 = str(uuid.uuid4())
        with patch(
            "backend.services.vpn.killswitch_service.KillSwitchService.bulk_enable",
            new_callable=AsyncMock,
            return_value={dev1: True, dev2: False},
        ):
            resp = await vpn_admin_client.post(
                "/api/v1/vpn/killswitch",
                json={
                    "device_ids": [dev1, dev2],
                    "action": "enable",
                    "method": "vpnservice",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "enable"
        assert data["total"] == 2
        assert data["success"] == 1

    @pytest.mark.asyncio
    async def test_disable_killswitch(self, vpn_admin_client):
        dev1 = str(uuid.uuid4())
        with patch(
            "backend.services.vpn.killswitch_service.KillSwitchService.disable_killswitch",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = await vpn_admin_client.post(
                "/api/v1/vpn/killswitch",
                json={"device_ids": [dev1], "action": "disable"},
            )
        assert resp.status_code == 200
        assert resp.json()["action"] == "disable"

    @pytest.mark.asyncio
    async def test_unknown_action_returns_400(self, vpn_admin_client):
        dev1 = str(uuid.uuid4())
        resp = await vpn_admin_client.post(
            "/api/v1/vpn/killswitch",
            json={"device_ids": [dev1], "action": "suspend"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_killswitch_requires_org_admin(self, vpn_manager_client):
        dev1 = str(uuid.uuid4())
        resp = await vpn_manager_client.post(
            "/api/v1/vpn/killswitch",
            json={"device_ids": [dev1], "action": "enable"},
        )
        assert resp.status_code == 403
