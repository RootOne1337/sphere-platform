"""A failed router DELETE cannot authorize reuse of a still-active tunnel IP."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.pool_service import VPNPoolService


@pytest.mark.parametrize("outcome", ["timeout", "http_500", "http_403", "http_202", "http_200", "http_204", "http_404"])
async def test_failed_revoke_retains_peer_and_address_reservation(world, outcome):
    w = world
    async with w.sessions() as db:
        peer = VPNPeer(org_id=w.org_a.id, device_id=w.dev_a.id,
            public_key="audit-peer", private_key_enc=b"synthetic", tunnel_ip="10.200.0.2")
        db.add(peer)
        await db.commit()
        pool = AsyncMock()
        service = VPNPoolService(db, pool, AWGConfigBuilder("audit-server", "127.0.0.1:9"),
            Fernet(Fernet.generate_key()), "http://127.0.0.1:9")

        def router_failure(request):
            if outcome == "timeout":
                raise httpx.ReadTimeout("isolated ambiguous DELETE response", request=request)
            return httpx.Response(int(outcome.removeprefix("http_")))

        await service._http.aclose()
        service._http = httpx.AsyncClient(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(router_failure))
        try:
            if outcome in {"http_200", "http_204", "http_404"}:
                await service.revoke_vpn(str(w.dev_a.id), w.org_a.id)
                await db.commit()
                await db.refresh(peer)
                assert peer.status == VPNPeerStatus.FREE
                assert peer.device_id is None
                assert not peer.is_active
                pool.release_ip.assert_not_awaited()
                return
            with pytest.raises(httpx.HTTPError):
                await service.revoke_vpn(str(w.dev_a.id), w.org_a.id)
            # Even a caller that commits after catching the error must retain the lease.
            await db.commit()
            await db.refresh(peer)
            assert peer.status == VPNPeerStatus.REVOKING
            assert peer.device_id == w.dev_a.id
            assert not peer.is_active
            pool.release_ip.assert_not_awaited()
        finally:
            await service.close()


async def test_concurrent_revoke_returns_address_only_once(world):
    w = world
    async with w.sessions() as first, w.sessions() as second:
        peer = VPNPeer(org_id=w.org_a.id, device_id=w.dev_a.id,
            public_key="audit-peer", private_key_enc=b"synthetic", tunnel_ip="10.200.0.2")
        first.add(peer)
        await first.commit()
        pool = AsyncMock()
        services = [VPNPoolService(db, pool, AWGConfigBuilder("audit-server", "127.0.0.1:9"),
            Fernet(Fernet.generate_key()), "http://127.0.0.1:9") for db in [first, second]]
        try:
            with (
                patch.object(services[0], "_remove_peer_from_server", AsyncMock()),
                patch.object(services[1], "_remove_peer_from_server", AsyncMock()) as repeated_delete,
            ):
                await services[0].revoke_vpn(str(w.dev_a.id), w.org_a.id)
                pending = asyncio.create_task(services[1].revoke_vpn(str(w.dev_a.id), w.org_a.id))
                try:
                    await asyncio.wait({pending}, timeout=0.15)
                    await first.commit()
                    await asyncio.wait_for(pending, 3)
                    await second.commit()
                finally:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                pool.release_ip.assert_not_awaited()
                await first.refresh(peer)
                assert peer.status == VPNPeerStatus.FREE
                repeated_delete.assert_not_awaited()
        finally:
            for service in services:
                await service.close()
