"""Isolated VPN lifecycle control: in-memory SQL and a simulated router."""
import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import tests.conftest  # noqa: F401 - project SQLite adapters
from backend.api.v1.vpn.router import get_pool_service, router
from backend.core.dependencies import get_current_user
from backend.database.engine import Base, get_db
from backend.models.device import Device
from backend.models.organization import Organization
from backend.services.vpn.awg_config import AWGConfigBuilder
from backend.services.vpn.health_monitor import NoopCommandPublisher, VPNHealthMonitor
from backend.services.vpn.ip_pool import IPPoolAllocator
from backend.services.vpn.pool_service import VPNPoolService


async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        org = Organization(name="VPN Audit", slug="vpn-audit")
        db.add(org)
        await db.flush()
        devices = {
            name: Device(org_id=org.id, name=name, serial=name)
            for name in ("never-assigned", "confirmed-revoke", "lost-revoke", "lost-assignment")
        }
        db.add_all(devices.values())
        await db.commit()
    device_ids = {name: str(device.id) for name, device in devices.items()}

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    provider_calls = []
    provider_keys = set()
    timeout_methods = set()
    cipher = Fernet(Fernet.generate_key())

    async def fake_provider(request):
        provider_calls.append(request.method)
        if request.method == "POST":
            provider_keys.add(json.loads(request.content)["public_key"])
        elif request.method == "DELETE":
            provider_keys.discard(request.url.path.removeprefix("/peers/"))
        if request.method in timeout_methods:
            raise httpx.ReadTimeout("synthetic provider reply lost", request=request)
        return httpx.Response(201 if request.method == "POST" else 204)

    async def database():
        async with sessions() as db:
            yield db

    async def pool():
        async with sessions() as db:
            service = VPNPoolService(
                db, IPPoolAllocator(None, "10.60.0.0/28"),
                AWGConfigBuilder("synthetic-router", "localhost:9"),
                cipher, "http://localhost:9",
            )
            await service.close()
            service._http = httpx.AsyncClient(
                base_url="http://localhost:9", transport=httpx.MockTransport(fake_provider)
            )
            try:
                yield service
            finally:
                await service.close()

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid4(), org_id=org.id, role="org_owner",
    )
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_pool_service] = pool

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://vpn-audit.invalid/api/v1/vpn/"
    ) as client:
        async def assign(name):
            return await client.post("assign", json={"device_id": device_ids[name]})

        async def revoke(*names):
            response = await client.post("revoke/bulk", json={"device_ids": [device_ids[n] for n in names]})
            assert response.status_code == 200
            return response.json()

        initial = await assign("confirmed-revoke")
        existing = await assign("confirmed-revoke")
        assert initial.status_code == existing.status_code == 200
        assert initial.json()["peer_id"] == existing.json()["peer_id"]
        assert provider_calls == ["POST"]
        provider_calls.clear()
        receipt = await revoke("never-assigned", "confirmed-revoke")
        assert receipt["succeeded"] == 2 and provider_calls == ["DELETE"]
        no_op_control = {"api_success": receipt["succeeded"], "provider_deletes": provider_calls.count("DELETE")}

        initial_assignment = await assign("lost-revoke")
        assert initial_assignment.status_code == 200
        lost_revoke_key = initial_assignment.json()["public_key"]
        assert lost_revoke_key in provider_keys
        timeout_methods.update(("POST", "DELETE"))
        unknown_revoke = await revoke("lost-revoke")
        assert unknown_revoke["results"][0]["success"] is False
        assert lost_revoke_key not in provider_keys
        unknown_assignment = await assign("lost-assignment")
        assert unknown_assignment.status_code == 503
        provider_calls.clear()
        assert (await assign("lost-assignment")).status_code == 409
        repeated_revoke = await client.delete(f"revoke/{device_ids['lost-revoke']}")
        assert repeated_revoke.status_code == 409
        assert provider_calls == []

        async with sessions() as db:
            monitor = VPNHealthMonitor(
                db, SimpleNamespace(wg_router_api_key=""), NoopCommandPublisher(), "http://localhost:9"
            )
            await monitor.close()
            monitor._http = httpx.AsyncClient(
                base_url="http://localhost:9", transport=httpx.MockTransport(fake_provider)
            )
            try:
                health_cycle = await monitor.check_all_peers(org.id)
            finally:
                await monitor.close()
        assert health_cycle["checked"] == 0 and provider_calls == []
        pending_readback = {}
        for name, expected in (("lost-assignment", "provisioning"), ("lost-revoke", "revoking")):
            response = await client.get("peers", params={"device_id": device_ids[name]})
            assert response.status_code == 200
            peer, = response.json()
            assert peer["status"] == expected
            assert "operation_id" not in peer and "updated_at" not in peer
            pending_readback[name] = peer["status"]

        print(json.dumps({
            "bulk_revoke_confirmed_and_no_op": no_op_control,
            "successful_assignment_repeated_same_peer_one_post": True,
            "provider_timeout_bulk_revoke_item_success": unknown_revoke["results"][0]["success"],
            "fake_provider_peer_after_timed_out_delete": "absent",
            "provider_timeout_assignment_http": unknown_assignment.status_code,
            "repeat_assignment_http": 409,
            "repeat_revoke_http": repeated_revoke.status_code,
            "provider_calls_on_repeat_and_health_cycle": len(provider_calls),
            "health_cycle_checked_pending_peers": health_cycle["checked"],
            "sql_peer_readback": pending_readback,
            "peer_receipt_has_operation_id_or_updated_at": False,
        }, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
