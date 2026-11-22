"""VPN authorization and retry contracts without contacting a router."""

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import HTTPException

from backend.models.vpn_peer import VPNPeer
from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.pool_service import VPNPoolService


@pytest_asyncio.fixture
async def vpn_service(world):
    async with world.sessions() as db:
        service = VPNPoolService(db, AsyncMock(), AWGConfigBuilder(
            server_public_key="audit-server-public-key", server_endpoint="127.0.0.1:9",
        ), Fernet(Fernet.generate_key()), wg_router_url="http://127.0.0.1:9")
        service.ip_pool.reserve_ip.return_value = "10.200.0.2"
        try:
            with patch.object(service, "_add_peer_to_server", AsyncMock()):
                yield service
        finally:
            await service.close()


async def test_vpn_assignment_rejects_foreign_device_before_any_allocation(world, vpn_service):
    svc = vpn_service
    with pytest.raises(HTTPException) as error:
        await svc.assign_vpn(str(world.dev_b.id), world.org_a.id)
    assert error.value.status_code == 404
    svc.ip_pool.reserve_ip.assert_not_awaited()
    svc._add_peer_to_server.assert_not_awaited()


async def test_idempotent_assignment_keeps_the_original_preshared_key(world, vpn_service):
    svc = vpn_service
    first = await svc.assign_vpn(str(world.dev_a.id), world.org_a.id)
    await svc.db.commit()
    repeated = await svc.assign_vpn(str(world.dev_a.id), world.org_a.id)
    first_psk = next(line for line in first.config.splitlines() if line.startswith("PresharedKey = "))
    assert first_psk in repeated.config.splitlines()
    assert first.config == repeated.config
    svc._add_peer_to_server.assert_awaited_once()
    peer = await svc.db.get(VPNPeer, uuid.UUID(first.peer_id))
    assert peer.preshared_key_enc is not None


async def test_concurrent_assignment_does_not_create_a_second_router_peer(world, vpn_service):
    svc = vpn_service
    first = await svc.assign_vpn(str(world.dev_a.id), world.org_a.id)
    async with world.sessions() as other_db:
        other = VPNPoolService(other_db, svc.ip_pool, svc.config_builder, svc.key_cipher,
            wg_router_url="http://127.0.0.1:9")
        try:
            with patch.object(other, "_add_peer_to_server", AsyncMock()) as add_peer:
                pending = asyncio.create_task(other.assign_vpn(str(world.dev_a.id), world.org_a.id))
                try:
                    await asyncio.wait({pending}, timeout=0.15)
                    await svc.db.commit()
                    repeated = await asyncio.wait_for(pending, 3)
                    await other_db.commit()
                finally:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                assert repeated.peer_id == first.peer_id
                assert repeated.config == first.config
                add_peer.assert_not_awaited()
                svc.ip_pool.reserve_ip.assert_awaited_once()
        finally:
            await other.close()
