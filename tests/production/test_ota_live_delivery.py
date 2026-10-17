"""Real PostgreSQL/RLS + Redis wake, grant ownership and revoke serialization."""
import asyncio
import json
import time
import uuid
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.datastructures import URL

from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.device import Device
from backend.services.device_ota_recovery import OtaRecoveryGrant
from backend.services.ota_delivery import dispatch_ota_wake
from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter


@pytest_asyncio.fixture
async def live_ota(runtime_db, monkeypatch):
    r, now = runtime_db, int(time.time())
    device = r.world.dev_a
    grant = OtaRecoveryGrant(command_id=uuid.uuid4(), sha256="a" * 64, version_name="candidate",
        version_code=10240, created_at=now, expires_at=now + 600, issued_before=now - 1).signed(device)
    async with r.world.sessions() as db:
        owned = await db.get(Device, device.id)
        owned.meta = {"ota_recovery": grant.model_dump(mode="json")}
        r.world.users["org_owner"].role = "super_admin"
        db.add(r.world.users["org_owner"])
        await db.commit()
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", r.sessions)
    previous = app.dependency_overrides[get_db]

    async def request_db():
        async with r.sessions() as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = request_db
    ws = AsyncMock()
    ws.base_url = URL("wss://socket-route.invalid/")
    manager = ConnectionManager()
    await manager.connect(ws, str(device.id), "android", str(device.org_id))
    try:
        yield r, device, grant, manager, ws
    finally:
        app.dependency_overrides[get_db] = previous


def wake(device, grant):
    return {"type": "_ota_recovery_wake", "org_id": str(device.org_id), "command_id": str(grant.command_id)}


async def test_api_and_socket_workers_share_a_real_redis_wake(live_ota):
    r, device, grant, manager, ws = live_ota
    router = PubSubRouter(r.world.redis, manager)
    await router.start()
    try:
        await router.subscribe_device(str(device.id), str(device.org_id))
        publisher = PubSubPublisher(r.world.redis)
        assert await publisher.send_command_live(str(device.id), wake(device, grant)) is True
        async with asyncio.timeout(4):
            while ws.send_json.await_count == 0:
                await asyncio.sleep(0.02)
        message = ws.send_json.await_args.args[0]
        assert message["type"] == "OTA_UPDATE" and message["command_id"] == str(grant.command_id)
        assert message["payload"]["download_url"] == "https://socket-route.invalid/api/v1/updates/artifacts/" + grant.sha256
        assert "authorization_tag" not in json.dumps(message)
        async with r.world.sessions() as db:
            assert (await db.get(Device, device.id)).meta["ota_recovery"] == grant.model_dump(mode="json")
    finally:
        await router.stop()


async def test_revoke_waits_for_live_send_and_does_not_remove_history(live_ota):
    r, device, grant, manager, ws = live_ota
    entered, release, revoked = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def send(_message):
        entered.set()
        await release.wait()

    ws.send_json.side_effect = send
    other_engine = create_async_engine(r.engine.url, poolclass=NullPool)
    other_sessions = async_sessionmaker(other_engine, expire_on_commit=False)

    async def revoke():
        async with other_sessions() as db:
            await bind_tenant_context(db, str(device.org_id))
            owned = await db.scalar(select(Device).where(Device.id == device.id).with_for_update())
            owned.meta = {"ota_recovery_receipts": [{"command_id": str(grant.command_id), "status": "failed"}]}
            await db.commit()
            revoked.set()

    sending = asyncio.create_task(dispatch_ota_wake(manager, str(device.id), wake(device, grant)))
    revoking = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        revoking = asyncio.create_task(revoke())
        await asyncio.sleep(0.15)
        assert not revoked.is_set(), "Revoke must wait on the actual row lock, not a process-local lock"
        release.set()
        await asyncio.wait_for(asyncio.gather(sending, revoking), timeout=3)
        assert revoked.is_set()
        ws.send_json.reset_mock()
        await dispatch_ota_wake(manager, str(device.id), wake(device, grant))
        ws.send_json.assert_not_awaited()
        async with r.world.sessions() as db:
            meta = (await db.get(Device, device.id)).meta
            assert "ota_recovery" not in meta and len(meta["ota_recovery_receipts"]) == 1
    finally:
        release.set()
        for task in [sending, revoking]:
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*[task for task in [sending, revoking] if task], return_exceptions=True)
        await other_engine.dispose()


@pytest.mark.parametrize("target", ["owned", "foreign"])
async def test_http_redispatch_is_tenant_scoped_and_keeps_grant_identity(live_ota, monkeypatch, target):
    r, device, grant, _, _ = live_ota
    publisher = Mock(send_command_live=AsyncMock(return_value=True))
    monkeypatch.setattr("backend.websocket.pubsub_router.get_pubsub_publisher", lambda: publisher)
    selected = device if target == "owned" else r.world.dev_b
    response = await r.world.client.post(f"/api/v1/updates/recovery/{selected.id}/dispatch",
        json={"command_id": str(grant.command_id)}, headers=r.world.auth(r.world.users["org_owner"]))
    assert response.status_code == (202 if target == "owned" else 404), response.text
    if target == "owned":
        assert response.json()["command_id"] == str(grant.command_id)
        assert "authorization_tag" not in response.text
        publisher.send_command_live.assert_awaited_once_with(str(device.id), wake(device, grant))
    else:
        publisher.send_command_live.assert_not_awaited()
    async with r.world.sessions() as db:
        assert (await db.get(Device, device.id)).meta["ota_recovery"] == grant.model_dump(mode="json")


async def test_viewer_can_inspect_but_cannot_dispatch_or_revoke(live_ota):
    r, device, grant, _, _ = live_ota
    auth = r.world.auth(r.world.users["viewer"])
    status = await r.world.client.get(f"/api/v1/updates/recovery/{device.id}", headers=auth)
    assert status.status_code == 200 and status.json()["state"] == "active"
    assert "authorization_tag" not in status.text
    dispatch = await r.world.client.post(f"/api/v1/updates/recovery/{device.id}/dispatch", json={"command_id": str(grant.command_id)}, headers=auth)
    revoke = await r.world.client.delete(f"/api/v1/updates/recovery/{device.id}?command_id={grant.command_id}", headers=auth)
    assert dispatch.status_code == revoke.status_code == 403
