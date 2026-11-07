"""Real transaction races and tenant isolation; disposable PostgreSQL only."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database.tenant import bind_tenant_context
from backend.models.device import Device
from backend.models.device_group import DeviceGroup
from backend.schemas.groups import CreateGroupRequest, UpdateGroupRequest
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
