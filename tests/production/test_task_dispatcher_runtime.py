"""Exercise the registered dispatcher with a real non-owner PostgreSQL login."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.device import Device
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus

LOOKUP = "sphere_auth.task_dispatch_work(text,uuid)"


@pytest_asyncio.fixture
async def dispatch_runtime(runtime_db, monkeypatch):
    from backend.api.v1.tasks import router
    from backend.services.task_dispatcher import TaskDispatchWorker

    r = runtime_db
    # Small UUIDs put only this test's devices at the front of the real lookup.
    # Close fixture tasks afterwards; unrelated audit records remain untouched.
    devices = [Device(id=uuid.UUID(int=uuid.uuid4().int >> 64), org_id=org.id, name="dispatch-probe")
               for org in (r.world.org_a, r.world.org_b)]
    async with r.world.sessions() as db:
        db.add_all(devices)
        await db.commit()
    async with r.world.engine.begin() as db:
        exists = await db.scalar(text("SELECT to_regprocedure(:lookup)"), {"lookup": LOOKUP})
        if exists:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION {LOOKUP} TO "{r.role}"'))
    cache, publisher, redis = AsyncMock(), AsyncMock(), AsyncMock()
    redis.keys.return_value = []
    publisher.send_command_live.return_value = True
    cache.bulk_get_status.side_effect = lambda ids: {
        value: SimpleNamespace(status="online") if value in {str(d.id) for d in devices} else None
        for value in ids
    }
    start = Mock()
    class FixtureWorker(TaskDispatchWorker):
        async def _discover(self, kind):
            # Execute the real bounded SQL discovery under the runtime role,
            # then avoid changing unrelated records in the shared audit DB.
            return [row for row in await super()._discover(kind)
                    if row[0] in {device.id for device in devices}]

    monkeypatch.setattr("backend.services.task_dispatcher.TaskDispatchWorker", FixtureWorker)
    monkeypatch.setattr(router, "AsyncSessionLocal", r.sessions)
    monkeypatch.setattr(router, "start_dispatcher", start)
    monkeypatch.setattr(router, "DeviceStatusCache", lambda client: cache if client is not None else None)
    monkeypatch.setattr("backend.database.redis_client.redis", redis)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", redis)
    monkeypatch.setattr("backend.websocket.pubsub_router.get_pubsub_publisher", lambda: publisher)
    try:
        yield SimpleNamespace(**locals())
    finally:
        async with r.world.sessions() as db:
            await db.execute(update(Task).where(Task.device_id.in_([d.id for d in devices])).values(
                status=TaskStatus.COMPLETED, cancel_requested_at=None, cancel_last_sent_at=None,
            ))
            await db.commit()
        if exists:
            async with r.world.engine.begin() as db:
                await db.execute(text(f'REVOKE EXECUTE ON FUNCTION {LOOKUP} FROM "{r.role}"'))


async def seed(r, *, cancel=False, device=None):
    device = device or r.devices[0]
    async with r.r.world.sessions() as db:
        script, version = r.r.world.script, r.r.world.version
        if device.org_id != script.org_id:
            script = Script(org_id=device.org_id, name="second-tenant-dispatch")
            db.add(script)
            await db.flush()
            version = ScriptVersion(org_id=device.org_id, script_id=script.id,
                                    dag={"nodes": [], "entry_node": "second-tenant"})
            db.add(version)
            await db.flush()
        task = Task(org_id=device.org_id, device_id=device.id,
                    script_id=script.id, script_version_id=version.id,
                    status=TaskStatus.RUNNING if cancel else TaskStatus.QUEUED,
                    cancel_requested_at=datetime.now(timezone.utc) if cancel else None)
        db.add(task)
        await db.commit()
        return task


@pytest.mark.parametrize("cancel", [False, True])
async def test_registered_tick_delivers_committed_intent_under_rls(dispatch_runtime, cancel):
    r = dispatch_runtime
    task = await seed(r, cancel=cancel)
    await r.router._startup_dispatcher()
    r.start.assert_called_once()
    await r.start.call_args.args[0]()
    commands = [c.args[1] for c in r.publisher.send_command_live.await_args_list]
    expected = f"user_cancel_{task.id}" if cancel else str(task.id)
    assert any(c["command_id"] == expected for c in commands)
    async with r.r.world.sessions() as db:
        current = await db.get(Task, task.id)
        assert current.status == (TaskStatus.RUNNING if cancel else TaskStatus.ASSIGNED)
        assert (current.cancel_last_sent_at is not None) == cancel


async def test_startup_without_redis_recovers_on_later_tick(dispatch_runtime, monkeypatch):
    r = dispatch_runtime
    task = await seed(r)
    monkeypatch.setattr("backend.database.redis_client.redis", None)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", None)
    await r.router._startup_dispatcher()
    r.start.assert_called_once()
    tick = r.start.call_args.args[0]
    await tick()
    r.publisher.send_command_live.assert_not_awaited()
    monkeypatch.setattr("backend.database.redis_client.redis", r.redis)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", r.redis)
    await tick()
    assert r.publisher.send_command_live.call_args.args[1]["command_id"] == str(task.id)


async def test_two_tenants_share_pool_without_context_leak_or_payload_mix(dispatch_runtime):
    r = dispatch_runtime
    tasks = [await seed(r, device=device) for device in r.devices]
    await r.router._startup_dispatcher()
    await r.start.call_args.args[0]()
    sent = {c.args[1]["command_id"]: c.args for c in r.publisher.send_command_live.await_args_list}
    assert set(sent) == {str(task.id) for task in tasks}
    for task in tasks:
        assert sent[str(task.id)][0] == str(task.device_id)
    assert sent[str(tasks[1].id)][1]["payload"]["dag"]["entry_node"] == "second-tenant"
    async with r.r.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id', true),'')")) is None


async def test_two_registered_workers_claim_once_and_ignore_legacy_redis_locks(dispatch_runtime):
    r = dispatch_runtime
    task = await seed(r)
    # Obsolete Redis bookkeeping cannot override committed PostgreSQL intent.
    await r.r.world.redis.set(f"task_running:{task.device_id}", str(task.id), ex=60)
    try:
        await r.router._startup_dispatcher()
        first = r.start.call_args.args[0]
        await r.router._startup_dispatcher()
        await asyncio.gather(first(), r.start.call_args.args[0]())
        r.publisher.send_command_live.assert_awaited_once()
        r.redis.keys.assert_not_awaited()
    finally:
        await r.r.world.redis.delete(f"task_running:{task.device_id}")


@pytest.mark.parametrize("cancel", [False, True])
async def test_lost_transport_reply_and_worker_restart_reuse_persisted_identity(dispatch_runtime, cancel):
    r = dispatch_runtime
    task = await seed(r, cancel=cancel)
    r.publisher.send_command_live.side_effect = ConnectionError("isolated lost reply")
    await r.router._startup_dispatcher()
    await r.start.call_args.args[0]()
    async with r.r.world.sessions() as db:
        current = await db.get(Task, task.id)
        assert current.status == (TaskStatus.RUNNING if cancel else TaskStatus.ASSIGNED)
        if cancel:
            current.cancel_last_sent_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        else:
            current.updated_at = datetime.now(timezone.utc) - timedelta(seconds=31)
        await db.commit()
    r.publisher.send_command_live.side_effect = None
    await r.router._startup_dispatcher()
    await r.start.call_args.args[0]()
    expected = f"user_cancel_{task.id}" if cancel else str(task.id)
    assert [c.args[1]["command_id"] for c in r.publisher.send_command_live.await_args_list] == [expected, expected]


async def test_presence_failure_keeps_cancel_delivery_and_recovers_assignment(dispatch_runtime):
    r = dispatch_runtime
    stop = await seed(r, cancel=True)
    task = await seed(r, device=r.devices[1])
    presence = r.cache.bulk_get_status.side_effect
    r.cache.bulk_get_status.side_effect = ConnectionError("isolated Redis failure")
    await r.router._startup_dispatcher()
    tick = r.start.call_args.args[0]
    with pytest.raises(ConnectionError):
        await tick()
    assert [c.args[1]["command_id"] for c in r.publisher.send_command_live.await_args_list] == [f"user_cancel_{stop.id}"]
    r.cache.bulk_get_status.side_effect = presence
    await tick()
    assert r.publisher.send_command_live.call_args.args[1]["command_id"] == str(task.id)


async def test_lookup_requires_grant_and_same_tick_recovers_after_grant(dispatch_runtime):
    r = dispatch_runtime
    task = await seed(r)
    await r.router._startup_dispatcher()
    tick = r.start.call_args.args[0]
    async with r.r.world.engine.begin() as db:
        await db.execute(text(f'REVOKE EXECUTE ON FUNCTION {LOOKUP} FROM "{r.r.role}"'))
    try:
        with pytest.raises(DBAPIError):
            await tick()
        r.publisher.send_command_live.assert_not_awaited()
    finally:
        async with r.r.world.engine.begin() as db:
            await db.execute(text(f'GRANT EXECUTE ON FUNCTION {LOOKUP} TO "{r.r.role}"'))
    await tick()
    assert r.publisher.send_command_live.call_args.args[1]["command_id"] == str(task.id)


async def test_offline_first_page_does_not_starve_next_device(dispatch_runtime):
    r = dispatch_runtime
    base = uuid.uuid4().int >> 80
    devices = [Device(id=uuid.UUID(int=base + index), org_id=r.r.world.org_a.id,
                      name="dispatch-page") for index in range(65)]
    async with r.r.world.sessions() as db:
        db.add_all(devices)
        await db.commit()
    r.devices.extend(devices)
    tasks = [await seed(r, device=device) for device in devices]
    online_id = str(devices[-1].id)
    r.cache.bulk_get_status.side_effect = lambda ids: {
        value: SimpleNamespace(status="online") if value == online_id else None for value in ids
    }
    await r.router._startup_dispatcher()
    tick = r.start.call_args.args[0]
    presence = r.cache.bulk_get_status.side_effect
    r.cache.bulk_get_status.side_effect = ConnectionError("isolated full-page cache failure")
    with pytest.raises(ConnectionError):
        await tick()
    r.cache.bulk_get_status.side_effect = presence
    await tick()
    r.publisher.send_command_live.assert_not_awaited()
    await tick()
    r.publisher.send_command_live.assert_awaited_once()
    assert r.publisher.send_command_live.call_args.args[1]["command_id"] == str(tasks[-1].id)
    assert max(len(call.args[0]) for call in r.cache.bulk_get_status.await_args_list) == 64


async def test_hung_send_releases_connection_and_does_not_block_other_tenant(dispatch_runtime):
    r = dispatch_runtime
    tasks = [await seed(r, device=device) for device in r.devices]
    healthy_sent, hung_cancelled = asyncio.Event(), asyncio.Event()

    async def send(device, command):
        # Actual pool has one connection. Send must happen after assignment commit.
        async with r.r.sessions() as db:
            assert await db.scalar(text("SELECT 1")) == 1
        async with r.r.world.sessions() as db:
            assert (await db.get(Task, uuid.UUID(command["command_id"]))).status == TaskStatus.ASSIGNED
        if device == str(tasks[0].device_id):
            try:
                await asyncio.Event().wait()
            finally:
                hung_cancelled.set()
        else:
            healthy_sent.set()
            return True

    r.publisher.send_command_live.side_effect = send
    await r.router._startup_dispatcher()
    tick_task = asyncio.create_task(r.start.call_args.args[0]())
    try:
        await asyncio.wait_for(healthy_sent.wait(), 1.5)
        assert not hung_cancelled.is_set()
        await asyncio.wait_for(tick_task, 4)
        assert hung_cancelled.is_set()
    finally:
        if not tick_task.done():
            tick_task.cancel()
        await asyncio.gather(tick_task, return_exceptions=True)


async def test_pending_cancel_fences_later_task_in_registered_worker(dispatch_runtime):
    r = dispatch_runtime
    stop = await seed(r, cancel=True)
    later = await seed(r)
    await r.router._startup_dispatcher()
    await r.start.call_args.args[0]()
    assert [c.args[1]["command_id"] for c in r.publisher.send_command_live.await_args_list] == [f"user_cancel_{stop.id}"]
    async with r.r.world.sessions() as db:
        assert (await db.get(Task, later.id)).status == TaskStatus.QUEUED


async def test_lost_commit_ack_does_not_immediately_replay_assignment(dispatch_runtime, monkeypatch):
    r = dispatch_runtime
    task = await seed(r)
    lost = False

    class LoseCommitAck(AsyncSession):
        async def commit(self):
            nonlocal lost
            assignment = any(isinstance(value, Task) and value.status == TaskStatus.ASSIGNED for value in self.dirty)
            await super().commit()
            if assignment and not lost:
                lost = True
                raise ConnectionError("isolated response lost after actual SQL commit")

    sessions = async_sessionmaker(r.r.engine, class_=LoseCommitAck, expire_on_commit=False)
    monkeypatch.setattr(r.router, "AsyncSessionLocal", sessions)
    await r.router._startup_dispatcher()
    tick = r.start.call_args.args[0]
    await tick()
    assert lost
    await tick()
    r.publisher.send_command_live.assert_not_awaited()
    async with r.r.world.sessions() as db:
        current = await db.get(Task, task.id)
        assert current.status == TaskStatus.ASSIGNED
        current.updated_at = datetime.now(timezone.utc) - timedelta(seconds=31)
        await db.commit()
    await tick()
    r.publisher.send_command_live.assert_awaited_once()
    assert r.publisher.send_command_live.call_args.args[1]["command_id"] == str(task.id)


async def test_sql_discovery_timeout_recovers_same_pool_and_worker(dispatch_runtime, monkeypatch):
    r = dispatch_runtime
    task = await seed(r)
    stalled = False

    class SlowDiscovery(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            nonlocal stalled
            if "sphere_auth.task_dispatch_work" in str(statement) and not stalled:
                stalled = True
                await super().execute(text("SELECT pg_sleep(5)"))
            return await super().execute(statement, *args, **kwargs)

    monkeypatch.setattr("backend.services.task_dispatcher.DISCOVERY_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(r.router, "AsyncSessionLocal", async_sessionmaker(
        r.r.engine, class_=SlowDiscovery, expire_on_commit=False,
    ))
    await r.router._startup_dispatcher()
    tick = r.start.call_args.args[0]
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(tick(), 2)
    r.publisher.send_command_live.assert_not_awaited()
    monkeypatch.setattr("backend.services.task_dispatcher.DISCOVERY_TIMEOUT_SECONDS", 5)
    await tick()
    r.publisher.send_command_live.assert_awaited_once()
    assert r.publisher.send_command_live.call_args.args[1]["command_id"] == str(task.id)
