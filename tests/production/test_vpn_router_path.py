"""Router route failures are not authoritative proof that a peer was removed."""

import httpx
import pytest
from cryptography.fernet import Fernet

from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.ip_pool import IPPoolAllocator
from backend.services.vpn.pool_service import VPNPoolService


async def test_public_key_is_encoded_as_one_delete_path_component(world):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(204)

    async with world.sessions() as db:
        svc = VPNPoolService(db, IPPoolAllocator(None), AWGConfigBuilder("audit-server", "127.0.0.1:9"),
                             Fernet(Fernet.generate_key()), "http://127.0.0.1:9")
        await svc._http.aclose()
        svc._http = httpx.AsyncClient(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(handle))
        try:
            await svc._remove_peer_from_server("audit/a+b=")
        finally:
            await svc.close()
    assert requests[0].url.raw_path == b"/peers/audit%2Fa%2Bb%3D"


async def test_generic_route_not_found_does_not_confirm_peer_deletion(world):
    async with world.sessions() as db:
        svc = VPNPoolService(db, IPPoolAllocator(None), AWGConfigBuilder("audit-server", "127.0.0.1:9"),
                             Fernet(Fernet.generate_key()), "http://127.0.0.1:9")
        await svc._http.aclose()
        svc._http = httpx.AsyncClient(base_url="http://127.0.0.1:9", transport=httpx.MockTransport(
            lambda request: httpx.Response(404, json={"detail": "Not Found"}),
        ))
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await svc._remove_peer_from_server("audit-peer")
        finally:
            await svc.close()
