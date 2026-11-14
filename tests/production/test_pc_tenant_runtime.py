"""PC endpoint/registration SQL with actual non-owner credentials; socket double."""

import asyncio
import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from _sockets import FakeSocket
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect
from test_device_bootstrap_runtime import issue_key, wait_for_two_runtime_locks

from backend.models.api_key import APIKey
from backend.models.ldplayer_instance import LDPlayerInstance
from backend.models.workstation import Workstation

router = importlib.import_module("backend.api.ws.agent.router")


class MessageSocket(FakeSocket):
    """Feed the real receive loop; transport/disconnect remain explicit doubles."""

    def __init__(self, token, messages):
        super().__init__([{"token": token}])
        self.incoming = iter(messages)

    async def receive(self):
        try:
            return {"type": "websocket.receive", "text": json.dumps(next(self.incoming))}
        except StopIteration:
            raise WebSocketDisconnect()


@pytest_asyncio.fixture
async def pc_runtime(runtime_db, monkeypatch):
    r = runtime_db
    async with r.world.sessions() as db:
        own = Workstation(org_id=r.world.org_a.id, name="isolated-pc")
        foreign = Workstation(org_id=r.world.org_b.id, name="isolated-foreign-pc")
        db.add_all([own, foreign])
        await db.flush()
        instance = LDPlayerInstance(org_id=own.org_id, workstation_id=own.id, instance_index=0)
        db.add(instance)
        await db.commit()
    manager = SimpleNamespace(connect=AsyncMock(return_value="pc-session"), disconnect=AsyncMock(return_value=False))
    monkeypatch.setattr(router, "AsyncSessionLocal", r.sessions)
    monkeypatch.setattr(router, "get_connection_manager", lambda: manager)
    monkeypatch.setattr(router, "get_redis", AsyncMock(return_value=r.world.redis))
    monkeypatch.setattr("backend.websocket.pubsub_router.get_pubsub_router", lambda: None)
    return SimpleNamespace(db=r, world=r.world, own=own, foreign=foreign, instance=instance, manager=manager)


def payload():
    return {"hostname": "isolated-host", "os_version": "isolated-os", "agent_version": "audit",
            "instances": [{"index": 0, "android_serial": "isolated-serial", "adb_port": 5555, "name": "test-instance"}]}


async def unscoped(r):
    async with r.db.sessions() as db:
        assert await db.scalar(text("SELECT current_user")) == r.db.role
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id',true),'')")) is None
        assert await db.scalar(select(func.count()).select_from(Workstation)) == 0
        assert await db.scalar(select(func.count()).select_from(LDPlayerInstance)) == 0


async def test_runtime_pc_auth_connects_and_reconnects(pc_runtime):
    r = pc_runtime
    _, raw = await issue_key(r.world)
    for attempt in range(2):
        data = payload() | {"hostname": f"isolated-host-{attempt}"}
        ws = MessageSocket(raw, [{"type": "workstation_register", "payload": data}])
        await router.pc_agent_ws(ws, str(r.own.id))
        assert ws.closed == []
        assert r.manager.connect.await_count == attempt + 1
        assert r.manager.connect.call_args.args[1:] == (str(r.own.id), "pc", str(r.own.org_id))
        assert r.manager.disconnect.await_count == attempt + 1
        async with r.world.sessions() as db:
            assert (await db.get(Workstation, r.own.id)).hostname == data["hostname"]
            assert (await db.get(LDPlayerInstance, r.instance.id)).android_serial == "isolated-serial"
        await unscoped(r)


@pytest.mark.parametrize("rejected", ["inactive", "expired", "permissions", "type", "unknown", "foreign_workstation"])
async def test_runtime_pc_auth_denies_bad_key_or_workstation(pc_runtime, rejected):
    r = pc_runtime
    key, raw = await issue_key(r.world)
    async with r.world.sessions() as db:
        saved = await db.get(APIKey, key.id)
        if rejected == "inactive":
            saved.is_active = False
        elif rejected == "expired":
            saved.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        elif rejected == "permissions":
            saved.permissions = []
        elif rejected == "type":
            saved.type = "user"
        elif rejected == "unknown":
            raw = "unknown-key"
        await db.commit()
    ws = FakeSocket([{"token": raw}])
    await router.pc_agent_ws(ws, str(r.foreign.id if rejected == "foreign_workstation" else r.own.id))
    r.manager.connect.assert_not_awaited()
    assert len(ws.closed) == 1
    assert ws.closed[0][0] == (4004 if rejected == "foreign_workstation" else 4001)
    await unscoped(r)


async def test_runtime_pc_registration_persists_and_caches_owned_instances(pc_runtime):
    r = pc_runtime
    data = payload()
    async with r.db.sessions() as db:
        await router.handle_workstation_register(str(r.own.id), data, str(r.own.org_id), db)
    async with r.world.sessions() as db:
        saved = await db.get(Workstation, r.own.id)
        assert saved.hostname == "isolated-host" and saved.is_online
        assert saved.last_heartbeat_at is not None
        assert (await db.get(LDPlayerInstance, r.instance.id)).android_serial == "isolated-serial"
    cached = await r.world.redis.get(f"topology:workstation:{r.own.id}")
    assert json.loads(cached) == data
    assert 0 < await r.world.redis.ttl(f"topology:workstation:{r.own.id}") <= 3600
    await unscoped(r)


async def test_runtime_pc_registration_cannot_write_foreign_workstation(pc_runtime):
    r = pc_runtime
    async with r.db.sessions() as db:
        await router.handle_workstation_register(str(r.foreign.id), payload(), str(r.own.org_id), db)
    async with r.world.sessions() as db:
        assert (await db.get(Workstation, r.foreign.id)).hostname is None
    assert not await r.world.redis.exists(f"topology:workstation:{r.foreign.id}")
    await unscoped(r)


async def test_runtime_pc_registration_sql_abort_then_new_session_recovers(pc_runtime, monkeypatch):
    r = pc_runtime
    reached = []
    async with r.db.sessions() as db:
        async def abort_commit():
            await db.flush()
            reached.append(True)
            await db.execute(text("SELECT 1/0"))
        monkeypatch.setattr(db, "commit", abort_commit)
        await router.handle_workstation_register(str(r.own.id), payload(), str(r.own.org_id), db)
    assert reached == [True]
    async with r.world.sessions() as db:
        assert (await db.get(Workstation, r.own.id)).hostname is None
        assert (await db.get(LDPlayerInstance, r.instance.id)).android_serial is None
    assert not await r.world.redis.exists(f"topology:workstation:{r.own.id}")
    async with r.db.sessions() as db:
        await router.handle_workstation_register(str(r.own.id), payload(), str(r.own.org_id), db)
    async with r.world.sessions() as db:
        assert (await db.get(Workstation, r.own.id)).hostname == "isolated-host"
    await unscoped(r)


async def test_runtime_pc_cache_failure_does_not_undo_registration(pc_runtime, monkeypatch):
    r = pc_runtime
    monkeypatch.setattr(r.world.redis, "setex", AsyncMock(side_effect=ConnectionError("isolated Redis failure")))
    async with r.db.sessions() as db:
        await router.handle_workstation_register(str(r.own.id), payload(), str(r.own.org_id), db)
    async with r.world.sessions() as db:
        assert (await db.get(Workstation, r.own.id)).hostname == "isolated-host"
        assert (await db.get(LDPlayerInstance, r.instance.id)).android_serial == "isolated-serial"
    await unscoped(r)


async def test_runtime_pc_auth_uses_revocation_committed_during_key_wait(pc_runtime, monkeypatch):
    r = pc_runtime
    key, raw = await issue_key(r.world)
    engine = create_async_engine(r.db.engine.url, pool_size=2, max_overflow=0)
    monkeypatch.setattr(router, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    sockets = [FakeSocket([{"token": raw}]) for _ in range(2)]
    calls = []
    try:
        async with r.world.sessions() as blocker:
            saved = await blocker.scalar(select(APIKey).where(APIKey.id == key.id).with_for_update())
            calls = [asyncio.create_task(router.pc_agent_ws(ws, str(r.own.id))) for ws in sockets]
            await wait_for_two_runtime_locks(r.db)
            saved.is_active = False
            await blocker.commit()
        await asyncio.gather(*calls)
        r.manager.connect.assert_not_awaited()
        assert all(len(ws.closed) == 1 and ws.closed[0][0] == 4001 for ws in sockets)
    finally:
        for call in calls:
            if not call.done():
                call.cancel()
        await asyncio.gather(*calls, return_exceptions=True)
        await engine.dispose()
