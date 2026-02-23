# tests/vpn/test_pool_service.py  TZ-06 SPLIT-2
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus

# ---------------------------------------------------------------------------
# IPPoolAllocator unit tests
# ---------------------------------------------------------------------------

class TestIPPoolAllocator:

    @pytest.mark.asyncio
    async def test_initialize_fills_pool(self, ip_pool, pool_redis):
        await ip_pool.initialize_pool("org-1", count=5)
        size = await ip_pool.pool_size("org-1")
        assert size == 5

    @pytest.mark.asyncio
    async def test_allocate_returns_ip(self, ip_pool, pool_redis):
        await ip_pool.initialize_pool("org-1", count=3)
        ip = await ip_pool.allocate_ip("org-1")
        assert ip is not None
        assert ip.startswith("10.100.0.")

    @pytest.mark.asyncio
    async def test_allocate_is_atomic_decrements_pool(self, ip_pool, pool_redis):
        await ip_pool.initialize_pool("org-2", count=5)
        ip1 = await ip_pool.allocate_ip("org-2")
        ip2 = await ip_pool.allocate_ip("org-2")
        assert ip1 != ip2
        assert await ip_pool.pool_size("org-2") == 3

    @pytest.mark.asyncio
    async def test_allocate_empty_pool_returns_none(self, ip_pool, pool_redis):
        ip = await ip_pool.allocate_ip("empty-org")
        assert ip is None

    @pytest.mark.asyncio
    async def test_release_returns_ip_to_pool(self, ip_pool, pool_redis):
        await ip_pool.initialize_pool("org-3", count=2)
        ip = await ip_pool.allocate_ip("org-3")
        assert await ip_pool.pool_size("org-3") == 1
        await ip_pool.release_ip("org-3", ip)
        assert await ip_pool.pool_size("org-3") == 2

    @pytest.mark.asyncio
    async def test_pool_covers_valid_subnet_ips(self, ip_pool, pool_redis):
        import ipaddress
        await ip_pool.initialize_pool("org-4", count=10)
        network = ipaddress.ip_network("10.100.0.0/24", strict=False)
        hosts = {str(h) for h in list(network.hosts())[:10]}
        # Drain all 10 IPs
        ips = set()
        for _ in range(10):
            ip = await ip_pool.allocate_ip("org-4")
            ips.add(ip)
        assert ips == hosts


# ---------------------------------------------------------------------------
# VPNPoolService unit tests
# ---------------------------------------------------------------------------

class TestVPNPoolService:

    @pytest.mark.asyncio
    async def test_assign_creates_peer_in_db(self, pool_service, db_session, test_org, test_device, pool_redis):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)

        assignment = await pool_service.assign_vpn(
            device_id=str(test_device.id),
            org_id=test_org.id,
        )

        assert assignment.assigned_ip.startswith("10.100.0.")
        assert assignment.config != ""
        assert assignment.qr_code != ""
        assert assignment.peer_id != ""

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.device_id == test_device.id)
        )
        peer = result.scalar_one()
        assert peer.status == VPNPeerStatus.ASSIGNED
        assert peer.tunnel_ip == assignment.assigned_ip

    @pytest.mark.asyncio
    async def test_assign_idempotent_returns_existing(self, pool_service, db_session, test_org, test_device, pool_redis):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)

        a1 = await pool_service.assign_vpn(str(test_device.id), test_org.id)
        a2 = await pool_service.assign_vpn(str(test_device.id), test_org.id)

        assert a1.assigned_ip == a2.assigned_ip
        assert a1.peer_id == a2.peer_id

    @pytest.mark.asyncio
    async def test_assign_pool_exhausted_raises_503(self, pool_service, test_org, test_device):
        from fastapi import HTTPException
        # Pool empty  no initialize_pool call
        with pytest.raises(HTTPException) as exc_info:
            await pool_service.assign_vpn(str(test_device.id), test_org.id)
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_assign_returns_ip_to_pool_on_failure(self, pool_service, test_org, test_device, pool_redis):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=3)

        # Make WG server call fail
        pool_service._add_peer_to_server = AsyncMock(side_effect=RuntimeError("WG down"))

        with pytest.raises(Exception):
            await pool_service.assign_vpn(str(test_device.id), test_org.id)

        # IP must be returned to pool
        size = await pool_service.ip_pool.pool_size(str(test_org.id))
        assert size == 3

    @pytest.mark.asyncio
    async def test_revoke_frees_peer_and_returns_ip(self, pool_service, db_session, test_org, test_device, pool_redis):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        assignment = await pool_service.assign_vpn(str(test_device.id), test_org.id)
        size_after_assign = await pool_service.ip_pool.pool_size(str(test_org.id))

        await pool_service.revoke_vpn(str(test_device.id), test_org.id)

        size_after_revoke = await pool_service.ip_pool.pool_size(str(test_org.id))
        assert size_after_revoke == size_after_assign + 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.tunnel_ip == assignment.assigned_ip)
        )
        peer = result.scalar_one()
        assert peer.status == VPNPeerStatus.FREE
        assert peer.device_id is None

    @pytest.mark.asyncio
    async def test_revoke_nonexistent_is_noop(self, pool_service, test_org):
        # Should not raise
        await pool_service.revoke_vpn("00000000-0000-0000-0000-000000000001", test_org.id)

    @pytest.mark.asyncio
    async def test_private_key_stored_encrypted(self, pool_service, db_session, test_org, test_device, pool_redis):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.device_id == test_device.id)
        )
        peer = result.scalar_one()
        # Encrypted bytes should not be a valid base64 WireGuard key plaintext
        assert len(peer.private_key_enc) > 44
        # Must be decryptable by the same cipher
        decrypted = pool_service.key_cipher.decrypt(peer.private_key_enc)
        assert len(decrypted) > 0

    @pytest.mark.asyncio
    async def test_obfuscation_params_stored(self, pool_service, db_session, test_org, test_device, pool_redis):
        await pool_service.ip_pool.initialize_pool(str(test_org.id), count=5)
        await pool_service.assign_vpn(str(test_device.id), test_org.id)

        from sqlalchemy import select
        result = await db_session.execute(
            select(VPNPeer).where(VPNPeer.device_id == test_device.id)
        )
        peer = result.scalar_one()
        assert peer.awg_jc is not None
        assert peer.awg_h1 is not None
