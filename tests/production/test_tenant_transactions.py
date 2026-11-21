"""Tenant context must follow the Session, never the pooled PostgreSQL connection."""

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from backend.core.dependencies import get_tenant_db
from backend.database.engine import get_db_session
from backend.models import Device


async def visible_devices(db):
    return set((await db.scalars(text("SELECT id FROM devices"))).all())


@pytest.mark.parametrize("entry", ["http", "background"])
@pytest.mark.parametrize("ending", ["commit", "rollback", "sql_error", "disconnect"])
async def test_tenant_access_survives_transaction_recovery(runtime_db, monkeypatch, entry, ending):
    w = runtime_db.world
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", runtime_db.sessions)
    context = get_db_session(org_id=str(w.org_a.id)) if entry == "background" else runtime_db.sessions()
    async with context as db:
        if entry == "http":
            await get_tenant_db(db=db, current_user=w.users["viewer"])
        expected = {w.dev_a.id, w.dev_a2.id}
        assert await visible_devices(db) == expected
        pid = await db.scalar(text("SELECT pg_backend_pid()"))
        if ending == "sql_error":
            with pytest.raises(DBAPIError):
                await db.execute(text("SELECT 1/0"))
            await db.rollback()
        elif ending == "disconnect":
            await db.invalidate()  # Close this test's DB connection and obtain a new one.
            await db.rollback()
        else:
            await getattr(db, ending)()
        assert await visible_devices(db) == expected
        new_pid = await db.scalar(text("SELECT pg_backend_pid()"))
        assert (new_pid != pid) if ending == "disconnect" else (new_pid == pid)
        result = await db.execute(text("UPDATE devices SET name='transaction-recovered' WHERE id=:id"), {"id": w.dev_a.id})
        assert result.rowcount == 1
        assert (await db.execute(text("UPDATE devices SET name='foreign' WHERE id=:id"), {"id": w.dev_b.id})).rowcount == 0


@pytest.mark.parametrize("ending", ["commit", "rollback"])
async def test_fresh_session_on_same_connection_cannot_inherit_previous_tenant(runtime_db, ending):
    w = runtime_db.world
    async with runtime_db.sessions() as first:
        await get_tenant_db(db=first, current_user=w.users["viewer"])
        pid = await first.scalar(text("SELECT pg_backend_pid()"))
        assert await visible_devices(first) == {w.dev_a.id, w.dev_a2.id}
        await getattr(first, ending)()
    async with runtime_db.sessions() as second:
        assert await second.scalar(text("SELECT pg_backend_pid()")) == pid
        assert await second.scalar(text("SELECT current_setting('app.current_org_id', true)")) in (None, "")
        assert await visible_devices(second) == set()
        await get_tenant_db(db=second, current_user=w.users["foreign"])
        assert await visible_devices(second) == {w.dev_b.id}


async def test_interleaved_tenants_reapply_own_context_on_one_shared_connection(runtime_db):
    w = runtime_db.world
    released_a, finished_b = asyncio.Event(), asyncio.Event()

    async def tenant_a():
        async with runtime_db.sessions() as db:
            await get_tenant_db(db=db, current_user=w.users["viewer"])
            pid = await db.scalar(text("SELECT pg_backend_pid()"))
            assert await visible_devices(db) == {w.dev_a.id, w.dev_a2.id}
            await db.commit()
            released_a.set()
            await asyncio.wait_for(finished_b.wait(), 5)
            assert await visible_devices(db) == {w.dev_a.id, w.dev_a2.id}
            return pid

    async def tenant_b():
        await asyncio.wait_for(released_a.wait(), 5)
        try:
            async with runtime_db.sessions() as db:
                await get_tenant_db(db=db, current_user=w.users["foreign"])
                pid = await db.scalar(text("SELECT pg_backend_pid()"))
                assert await visible_devices(db) == {w.dev_b.id}
                await db.commit()
                return pid
        finally:
            finished_b.set()

    pid_a, pid_b = await asyncio.gather(tenant_a(), tenant_b())
    assert pid_a == pid_b


@pytest.mark.parametrize("after_commit", [False, True])
async def test_session_cannot_switch_tenant_with_cached_orm_identity(runtime_db, after_commit):
    w = runtime_db.world
    async with runtime_db.sessions() as db:
        await get_tenant_db(db=db, current_user=w.users["viewer"])
        cached = await db.get(Device, w.dev_a.id)
        assert cached is not None
        if after_commit:
            await db.commit()
        try:
            await get_tenant_db(db=db, current_user=w.users["foreign"])
        except ValueError as exc:
            assert "tenant" in str(exc)
        else:
            assert await db.get(Device, w.dev_a.id) is cached
            assert await db.get(Device, w.dev_b.id) is not None
            pytest.fail("One Session retains tenant A's ORM object and loads tenant B after rebinding")
        assert await db.get(Device, w.dev_a.id) is cached
        assert set((await db.scalars(select(Device.id))).all()) == {w.dev_a.id, w.dev_a2.id}


async def test_first_binding_inside_savepoint_is_rejected_before_context_can_be_rolled_back(runtime_db):
    async with runtime_db.sessions() as db:
        await db.execute(text("SELECT 1"))
        savepoint = await db.begin_nested()
        with pytest.raises(ValueError, match="savepoint"):
            await get_tenant_db(db=db, current_user=runtime_db.world.users["viewer"])
        await savepoint.rollback()
        assert await visible_devices(db) == set()


async def test_existing_binding_survives_savepoint_rollback_and_repeat_binding(runtime_db):
    w = runtime_db.world
    async with runtime_db.sessions() as db:
        await get_tenant_db(db=db, current_user=w.users["viewer"])
        savepoint = await db.begin_nested()
        await get_tenant_db(db=db, current_user=w.users["viewer"])
        assert await visible_devices(db) == {w.dev_a.id, w.dev_a2.id}
        await savepoint.rollback()
        assert await visible_devices(db) == {w.dev_a.id, w.dev_a2.id}
        await db.commit()
        assert await visible_devices(db) == {w.dev_a.id, w.dev_a2.id}


async def test_invalid_tenant_is_rejected_before_creating_transaction(runtime_db):
    async with runtime_db.sessions() as db:
        with pytest.raises(ValueError):
            await get_tenant_db(db=db, current_user=SimpleNamespace(org_id="not-a-uuid"))
        assert not db.in_transaction()
