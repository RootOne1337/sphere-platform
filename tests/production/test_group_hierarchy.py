"""Real transaction races and tenant isolation; disposable PostgreSQL only."""
import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.device import Device
from backend.models.device_group import DeviceGroup
from backend.models.schedule import Schedule
from backend.schemas.devices import UpdateDeviceRequest
from backend.schemas.groups import CreateGroupRequest, UpdateGroupRequest
from backend.services.cache_service import CacheService
from backend.services.device_service import DeviceService
from backend.services.group_service import GroupService


async def seed(world):
    async with world.sessions() as db:
        a = DeviceGroup(org_id=world.org_a.id, name="A")
        b = DeviceGroup(org_id=world.org_a.id, name="B")
        foreign = DeviceGroup(org_id=world.org_b.id, name="Foreign")
        db.add_all([a, b, foreign])
        await db.commit()
        return a, b, foreign


async def test_opposite_reparents_cannot_commit_a_cycle(world):
    a, b, _ = await seed(world)
    async with world.sessions() as holder, world.sessions() as competitor:
        await GroupService(holder).update_group(a.id, a.org_id, UpdateGroupRequest(parent_group_id=b.id))
        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(GroupService(competitor).update_group(
                b.id, b.org_id, UpdateGroupRequest(parent_group_id=a.id)), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        with pytest.raises(HTTPException) as cycle:
            await GroupService(competitor).update_group(b.id, b.org_id, UpdateGroupRequest(parent_group_id=a.id))
        assert cycle.value.status_code == 400
        await competitor.rollback()
    async with world.sessions() as observer:
        assert (await observer.get(DeviceGroup, a.id)).parent_group_id == b.id
        assert (await observer.get(DeviceGroup, b.id)).parent_group_id is None


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
async def test_group_writes_are_fenced_until_commit(world, operation):
    a, b, _ = await seed(world)
    async with world.sessions() as holder, world.sessions() as competitor:
        await GroupService(holder).update_group(a.id, a.org_id, UpdateGroupRequest(description="Held"))
        service = GroupService(competitor)

        async def write():
            if operation == "create":
                return await service.create_group(a.org_id, CreateGroupRequest(name="New"))
            if operation == "update":
                return await service.update_group(b.id, b.org_id, UpdateGroupRequest(description="Confirmed"))
            return await service.delete_group(b.id, b.org_id)

        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(write(), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        await asyncio.wait_for(write(), timeout=2)
        await competitor.commit()


async def test_other_organization_is_not_blocked(world):
    a, _, foreign = await seed(world)
    async with world.sessions() as holder, world.sessions() as other:
        await GroupService(holder).update_group(a.id, a.org_id, UpdateGroupRequest(description="Held"))
        result = await asyncio.wait_for(GroupService(other).update_group(
            foreign.id, foreign.org_id, UpdateGroupRequest(description="Independent")), timeout=2)
        assert result.description == "Independent"
        await other.commit()
        await holder.rollback()


async def test_rollback_releases_fence_and_does_not_persist_parent(world):
    a, b, _ = await seed(world)
    async with world.sessions() as holder:
        await GroupService(holder).update_group(a.id, a.org_id, UpdateGroupRequest(parent_group_id=b.id))
        await holder.rollback()
    async with world.sessions() as next_writer:
        result = await GroupService(next_writer).update_group(b.id, b.org_id, UpdateGroupRequest(parent_group_id=a.id))
        assert result.parent_group_id == a.id
        await next_writer.commit()
        assert (await next_writer.get(DeviceGroup, a.id)).parent_group_id is None


async def test_non_owner_role_can_clear_own_parent_but_cannot_use_foreign_parent(runtime_db):
    r = runtime_db
    a, b, foreign = await seed(r.world)

    @asynccontextmanager
    async def owned():
        async with r.sessions() as db:
            await bind_tenant_context(db, str(a.org_id))
            yield db

    async with owned() as db:
        service = GroupService(db)
        with pytest.raises(HTTPException) as hidden:
            await service.update_group(a.id, a.org_id, UpdateGroupRequest(parent_group_id=foreign.id))
        assert hidden.value.status_code == 404
        await db.rollback()
    async with owned() as db:
        service = GroupService(db)
        await service.update_group(a.id, a.org_id, UpdateGroupRequest(parent_group_id=b.id))
        await db.commit()
    async with owned() as db:
        result = await GroupService(db).update_group(a.id, a.org_id, UpdateGroupRequest(parent_group_id=None))
        assert result.parent_group_id is None
        await db.commit()
    async with r.sessions() as unscoped:
        assert not list(await unscoped.scalars(select(DeviceGroup).where(DeviceGroup.id.in_([a.id, b.id]))))


async def test_duplicate_create_after_owner_commit_returns_conflict(world):
    a, _, _ = await seed(world)
    async with world.sessions() as holder, world.sessions() as competitor:
        await GroupService(holder).create_group(a.org_id, CreateGroupRequest(name="Reserved"))
        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(GroupService(competitor).create_group(
                a.org_id, CreateGroupRequest(name="Reserved")), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        with pytest.raises(HTTPException) as duplicate:
            await GroupService(competitor).create_group(a.org_id, CreateGroupRequest(name="Reserved"))
        assert duplicate.value.status_code == 409
        await competitor.rollback()


async def test_stale_loaded_ancestry_does_not_authorize_a_cycle(world):
    a, b, _ = await seed(world)
    async with world.sessions() as observer, world.sessions() as writer:
        stale = await observer.get(DeviceGroup, a.id)
        assert stale.parent_group_id is None
        await GroupService(writer).update_group(a.id, a.org_id, UpdateGroupRequest(parent_group_id=b.id))
        await writer.commit()
        with pytest.raises(HTTPException) as invalid:
            await GroupService(observer).update_group(b.id, b.org_id, UpdateGroupRequest(parent_group_id=a.id))
        assert invalid.value.status_code == 400
        await observer.rollback()


async def test_delete_parent_preserves_child_and_device_memberships(world):
    a, b, _ = await seed(world)
    async with world.sessions() as db:
        await GroupService(db).update_group(b.id, b.org_id, UpdateGroupRequest(parent_group_id=a.id))
        device = await db.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.groups)))
        device.groups = [await db.get(DeviceGroup, a.id), await db.get(DeviceGroup, b.id)]
        await db.commit()
    async with world.sessions() as db:
        await GroupService(db).delete_group(a.id, a.org_id)
        await db.commit()
    async with world.sessions() as observer:
        assert (await observer.get(DeviceGroup, b.id)).parent_group_id is None
        device = await observer.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.groups)))
        assert {g.id for g in device.groups} == {b.id}


async def test_concurrent_membership_addition_and_replacement_are_fenced(world):
    a, b, _ = await seed(world)
    device_id = world.dev_a.id
    async with world.sessions() as holder, world.sessions() as competitor:
        first = await GroupService(holder).change_device_memberships([device_id], a.id, a.org_id, "add")
        assert first[0].outcome == "changed"
        with pytest.raises(HTTPException) as legacy_blocked:
            await asyncio.wait_for(DeviceService(competitor, CacheService()).update_device(
                device_id, a.org_id, UpdateDeviceRequest(group_id=b.id),
            ), timeout=2)
        assert legacy_blocked.value.status_code == 409
        await competitor.rollback()
        pending = asyncio.create_task(GroupService(competitor).change_device_memberships(
            [device_id], b.id, a.org_id, "add",
        ))
        await asyncio.sleep(0.05)
        assert not pending.done()
        await holder.commit()
        added = await asyncio.wait_for(pending, timeout=2)
        assert added[0].outcome == "changed"
        await competitor.commit()
    async with world.sessions() as observer:
        device = await observer.scalar(select(Device).where(Device.id == device_id).options(selectinload(Device.groups)))
        assert {group.id for group in device.groups} == {a.id, b.id}
        updated = await DeviceService(observer, CacheService()).update_device(
            device_id, a.org_id, UpdateDeviceRequest(group_id=b.id, name="Legacy update"),
        )
        await observer.commit()
        assert updated.name == "Legacy update"
        assert updated.group_ids == [b.id]


async def test_membership_api_reports_per_device_and_preserves_other_groups(runtime_db):
    world = runtime_db.world
    a, b, foreign = await seed(world)
    headers = world.auth(world.users["org_admin"])
    device_id = str(world.dev_a.id)
    retired = str(world.dev_a2.id)
    unavailable = [retired, str(world.dev_b.id), str(uuid.uuid4())]
    async with world.sessions() as db:
        device = await db.get(Device, world.dev_a2.id)
        device.is_active = False
        await db.commit()
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(a.org_id))
        await GroupService(db).change_device_memberships([world.dev_a.id], a.id, a.org_id, "add")
        await db.commit()

    async def runtime_session():
        async with runtime_db.sessions() as db:
            yield db

    async def mutate(operation, ids=None, group=b, auth=headers):
        with patch.dict(app.dependency_overrides, {get_db: runtime_session}):
            return await world.client.post(
                f"/api/v1/groups/{group.id}/devices/membership", headers=auth,
                json={"operation": operation, "device_ids": ids or [device_id, *unavailable]},
            )

    for operation, outcome in (("add", "changed"), ("add", "unchanged"), ("remove", "changed"), ("remove", "unchanged")):
        response = await mutate(operation)
        assert response.status_code == 200, response.text
        assert response.json() == {
            "group_id": str(b.id), "operation": operation,
            "results": [{"device_id": device_id, "outcome": outcome}, *[
                {"device_id": value, "outcome": "device_not_found"} for value in unavailable
            ]],
        }
    assert (await mutate("add", [device_id, device_id])).status_code == 422
    assert (await mutate("add", group=foreign)).status_code == 404
    assert (await mutate("add", auth=world.auth(world.users["viewer"]))).status_code == 403
    async with world.sessions() as db:
        device = await db.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.groups)))
        assert {group.id for group in device.groups} == {a.id}

    for outcome in ("changed", "unchanged"):
        response = await mutate("replace", [device_id])
        assert response.status_code == 200, response.text
        assert response.json()["results"] == [{"device_id": device_id, "outcome": outcome}]
    async with world.sessions() as db:
        device = await db.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.groups)))
        assert {group.id for group in device.groups} == {b.id}


async def test_concurrent_runtime_membership_requests_both_commit(runtime_db):
    world = runtime_db.world
    a, b, _ = await seed(world)
    device_id = world.dev_a.id
    missing = uuid.uuid4()
    headers = world.auth(world.users["org_admin"])

    async def add(group, devices):
        return await world.client.post(
            f"/api/v1/groups/{group.id}/devices/membership", headers=headers,
            json={"operation": "add", "device_ids": [str(item) for item in devices]},
        )

    # Keep two request connections plus the holder. The default
    # RLS fixture uses one connection to test tenant-context reuse.
    engine = create_async_engine(runtime_db.engine.url, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as holder:
            await bind_tenant_context(holder, str(a.org_id))
            await GroupService(holder).change_device_memberships([device_id], a.id, a.org_id, "add")
            request_entered = asyncio.Queue()

            async def request_session():
                async with sessions() as db:
                    await db.connection()
                    request_entered.put_nowait(True)
                    yield db

            # Both requests wait behind the holder and then commit their own
            # membership change on separate, normally authenticated sessions.
            with patch.dict(app.dependency_overrides, {get_db: request_session}):
                async with asyncio.timeout(4), asyncio.TaskGroup() as tasks:
                    mixed_request = tasks.create_task(add(a, [device_id, missing]))
                    second_request = tasks.create_task(add(b, [device_id]))
                    await request_entered.get()
                    await request_entered.get()
                    await asyncio.sleep(0.05)
                    assert not mixed_request.done()
                    assert not second_request.done()
                    await holder.rollback()
                mixed, second = mixed_request.result(), second_request.result()
        assert mixed.status_code == second.status_code == 200, (mixed.text, second.text)
        assert mixed.json()["results"] == [
            {"device_id": str(device_id), "outcome": "changed"},
            {"device_id": str(missing), "outcome": "device_not_found"},
        ]
        assert second.json()["results"] == [{"device_id": str(device_id), "outcome": "changed"}]
    finally:
        await engine.dispose()
    async with world.sessions() as db:
        device = await db.scalar(select(Device).where(Device.id == device_id).options(selectinload(Device.groups)))
        assert {group.id for group in device.groups} == {a.id, b.id}


async def test_delete_group_reports_schedule_dependency(world):
    a, b, _ = await seed(world)
    async with world.sessions() as db:
        schedule = Schedule(org_id=a.org_id, name="Group schedule", interval_seconds=3600,
                            group_id=a.id, target_type="script", script_id=world.script.id)
        db.add(schedule)
        await db.commit()
    headers = world.auth(world.users["org_admin"])
    blocked = await world.client.delete(f"/api/v1/groups/{a.id}", headers=headers)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Group is used by schedules"
    async with world.sessions() as db:
        assert await db.get(DeviceGroup, a.id) is not None
        assert await db.get(Schedule, schedule.id) is not None
    assert (await world.client.delete(f"/api/v1/groups/{b.id}", headers=headers)).status_code == 204
