"""Location geography and hierarchy contracts on disposable PostgreSQL/Redis."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database.tenant import bind_tenant_context
from backend.models.device import Device, DeviceStatus
from backend.models.location import Location
from backend.schemas.locations import CreateLocationRequest, UpdateLocationRequest
from backend.services.location_service import LocationService


async def seed(world):
    async with world.sessions() as db:
        a = Location(org_id=world.org_a.id, name="A", latitude=0, longitude=180)
        b = Location(org_id=world.org_a.id, name="B")
        foreign = Location(org_id=world.org_b.id, name="Foreign")
        db.add_all([a, b, foreign])
        await db.flush()
        b.parent_location_id = a.id
        await db.commit()
        return a, b, foreign


async def request(world, method, path, **kwargs):
    return await world.client.request(method, "/api/v1/locations" + path,
                                     headers=world.auth(world.users["org_admin"]), **kwargs)


async def test_descendant_cycle_is_rejected_atomically(world):
    a, b, _ = await seed(world)
    result = await request(world, "PUT", f"/{a.id}", json={"name": "Changed", "latitude": 10, "parent_location_id": str(b.id)})
    assert result.status_code == 400
    async with world.sessions() as db:
        row = await db.get(Location, a.id)
        assert (row.name, row.latitude, row.parent_location_id) == ("A", 0, None)


async def test_explicit_null_clears_nullable_fields_and_omission_retains(world):
    a, b, _ = await seed(world)
    result = await request(world, "PUT", f"/{b.id}", json={"description": "Retain", "latitude": 0, "longitude": -180})
    assert result.status_code == 200
    result = await request(world, "PUT", f"/{b.id}", json={"parent_location_id": None, "latitude": None, "longitude": None})
    assert result.status_code == 200
    assert result.json()["parent_location_id"] is None
    assert result.json()["latitude"] is None and result.json()["longitude"] is None
    assert result.json()["description"] == "Retain"
    result = await request(world, "PUT", f"/{b.id}", json={"description": None, "address": None, "color": None})
    assert result.status_code == 200 and result.json()["description"] is None


@pytest.mark.parametrize("body", [{"latitude": 90, "longitude": 180}, {"latitude": -90, "longitude": -180}, {"latitude": 0, "longitude": 0}])
async def test_valid_coordinate_boundaries_and_zero(world, body):
    result = await request(world, "POST", "", json={"name": "Geo", **body})
    assert result.status_code == 201
    assert all(result.json()[k] == v for k, v in body.items())


@pytest.mark.parametrize("body", [{"latitude": 90.01}, {"longitude": -180.01}, {"latitude": "NaN"}, {"longitude": "Infinity"}, {"name": None}, {"expected_updated_at": "2026-01-01T00:00:00"}, {"latitdue": 10}])
async def test_invalid_patch_does_not_write(world, body):
    a, _, _ = await seed(world)
    result = await request(world, "PUT", f"/{a.id}", json=body)
    assert result.status_code == 422
    async with world.sessions() as db:
        row = await db.get(Location, a.id)
        assert (row.name, row.latitude, row.longitude) == ("A", 0, 180)


@pytest.mark.parametrize("foreign", [True, False])
async def test_parent_not_owned_or_missing_is_404_and_atomic(world, foreign):
    a, _, other = await seed(world)
    result = await request(world, "PUT", f"/{a.id}", json={"name": "Changed", "parent_location_id": str(other.id if foreign else uuid.uuid4())})
    assert result.status_code == 404
    async with world.sessions() as db:
        assert (await db.get(Location, a.id)).name == "A"


async def test_detail_is_owned_and_counters_survive_update(world):
    a, _, foreign = await seed(world)
    async with world.sessions() as db:
        device = await db.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.locations)))
        device.locations = [await db.get(Location, a.id)]
        device.last_status = DeviceStatus.ONLINE
        await db.commit()
    result = await request(world, "GET", f"/{a.id}")
    assert result.status_code == 200
    assert (result.json()["total_devices"], result.json()["online_devices"]) == (1, 1)
    assert result.json()["updated_at"]
    result = await request(world, "PUT", f"/{a.id}", json={"address": "Updated"})
    assert result.status_code == 200
    assert (result.json()["total_devices"], result.json()["online_devices"]) == (1, 1)
    assert (await request(world, "GET", f"/{foreign.id}")).status_code == 404


async def test_stale_condition_cannot_overwrite_newer_geography(world):
    a, _, _ = await seed(world)
    before = (await request(world, "GET", f"/{a.id}")).json()
    condition = {"expected_updated_at": before["updated_at"]}
    result = await request(world, "PUT", f"/{a.id}", json={"latitude": 12, **condition})
    assert result.status_code == 200 and result.json()["updated_at"] != before["updated_at"]
    result = await request(world, "PUT", f"/{a.id}", json={"latitude": 20, **condition})
    assert result.status_code == 409
    assert (await request(world, "GET", f"/{a.id}")).json()["latitude"] == 12


@pytest.mark.parametrize("operation", ["create", "update", "delete", "assign", "remove"])
async def test_writers_are_fenced_until_commit_without_waiting(world, operation):
    a, b, _ = await seed(world)
    async with world.sessions() as holder, world.sessions() as competitor:
        await LocationService(holder).update_location(a.id, a.org_id, UpdateLocationRequest(address="Held"))
        service = LocationService(competitor)

        async def write():
            if operation == "create":
                return await service.create_location(a.org_id, CreateLocationRequest(name="New"))
            if operation == "update":
                return await service.update_location(b.id, b.org_id, UpdateLocationRequest(address="Changed"))
            if operation == "assign":
                return await service.assign_devices_to_location([str(world.dev_a.id)], b.id, b.org_id)
            if operation == "remove":
                return await service.remove_devices_from_location([str(world.dev_a.id)], b.id, b.org_id)
            return await service.delete_location(b.id, b.org_id)

        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(write(), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        await asyncio.wait_for(write(), timeout=2)
        await competitor.commit()


async def test_opposing_reparents_cannot_commit_a_cycle(world):
    a, b, _ = await seed(world)
    async with world.sessions() as db:
        await LocationService(db).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=None))
        await db.commit()
    async with world.sessions() as holder, world.sessions() as competitor:
        await LocationService(holder).update_location(a.id, a.org_id, UpdateLocationRequest(parent_location_id=b.id))
        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(LocationService(competitor).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=a.id)), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        with pytest.raises(HTTPException) as cycle:
            await LocationService(competitor).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=a.id))
        assert cycle.value.status_code == 400
        await competitor.rollback()


async def test_other_org_not_blocked_and_rollback_releases_fence(world):
    a, _, other = await seed(world)
    async with world.sessions() as holder, world.sessions() as outsider:
        await LocationService(holder).update_location(a.id, a.org_id, UpdateLocationRequest(address="Held"))
        result = await asyncio.wait_for(LocationService(outsider).update_location(other.id, other.org_id, UpdateLocationRequest(address="Independent")), timeout=2)
        assert result.address == "Independent"
        await outsider.commit()
        await holder.rollback()
    async with world.sessions() as db:
        assert (await db.get(Location, a.id)).address is None
        await LocationService(db).update_location(a.id, a.org_id, UpdateLocationRequest(address="Released"))
        await db.commit()


async def test_runtime_rls_hides_foreign_locations_and_allows_own_clear(runtime_db):
    r = runtime_db
    a, b, other = await seed(r.world)
    async with r.sessions() as db:
        await bind_tenant_context(db, str(a.org_id))
        with pytest.raises(HTTPException) as hidden:
            await LocationService(db).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=other.id))
        assert hidden.value.status_code == 404
        await db.rollback()
    async with r.sessions() as db:
        await bind_tenant_context(db, str(a.org_id))
        result = await LocationService(db).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=None))
        assert result.parent_location_id is None
        await db.commit()
    async with r.sessions() as db:
        assert not list(await db.scalars(select(Location)))


async def test_delete_parent_preserves_child_and_devices(world):
    a, b, _ = await seed(world)
    async with world.sessions() as db:
        device = await db.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.locations)))
        device.locations = [await db.get(Location, a.id), await db.get(Location, b.id)]
        await db.commit()
    result = await request(world, "DELETE", f"/{a.id}")
    assert result.status_code == 204
    async with world.sessions() as db:
        assert (await db.get(Location, b.id)).parent_location_id is None
        device = await db.scalar(select(Device).where(Device.id == world.dev_a.id).options(selectinload(Device.locations)))
        assert {loc.id for loc in device.locations} == {b.id}


async def test_viewer_can_read_but_cannot_write(world):
    a, _, _ = await seed(world)
    auth = world.auth(world.users["viewer"])
    assert (await world.client.get(f"/api/v1/locations/{a.id}", headers=auth)).status_code == 200
    for method, path, body in [("POST", "", {"name": "No"}), ("PUT", f"/{a.id}", {"address": "No"}), ("DELETE", f"/{a.id}", None)]:
        result = await world.client.request(method, "/api/v1/locations" + path, headers=auth, **({"json": body} if body else {}))
        assert result.status_code == 403


async def test_stale_delete_condition_preserves_location(world):
    a, _, _ = await seed(world)
    baseline = (await request(world, "GET", f"/{a.id}")).json()
    assert (await request(world, "PUT", f"/{a.id}", json={"address": "Changed"})).status_code == 200
    result = await request(world, "DELETE", f"/{a.id}", params={"expected_updated_at": baseline["updated_at"]})
    assert result.status_code == 409
    fresh = (await request(world, "GET", f"/{a.id}")).json()
    assert fresh["address"] == "Changed"
    assert (await request(world, "DELETE", f"/{a.id}", params={"expected_updated_at": "2026-01-01T00:00:00"})).status_code == 422
    assert (await request(world, "DELETE", f"/{a.id}", params={"expected_updated_at": fresh["updated_at"]})).status_code == 204


async def test_self_parent_and_inherited_legacy_cycle_are_rejected(world):
    a, b, _ = await seed(world)
    assert (await request(world, "PUT", f"/{a.id}", json={"parent_location_id": str(a.id)})).status_code == 400
    async with world.sessions() as db:
        (await db.get(Location, a.id)).parent_location_id = b.id
        await db.commit()
    assert (await request(world, "POST", "", json={"name": "Invalid inherited ancestry", "parent_location_id": str(a.id)})).status_code == 400
    assert (await request(world, "PUT", f"/{a.id}", json={"parent_location_id": None})).status_code == 200


async def test_duplicate_create_returns_conflict_after_commit(world):
    a, _, _ = await seed(world)
    async with world.sessions() as holder, world.sessions() as competitor:
        await LocationService(holder).create_location(a.org_id, CreateLocationRequest(name="Reserved"))
        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(LocationService(competitor).create_location(a.org_id, CreateLocationRequest(name="Reserved")), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        with pytest.raises(HTTPException) as duplicate:
            await LocationService(competitor).create_location(a.org_id, CreateLocationRequest(name="Reserved"))
        assert duplicate.value.status_code == 409


async def test_stale_identity_map_does_not_authorize_cycle(world):
    a, b, _ = await seed(world)
    async with world.sessions() as reader, world.sessions() as writer:
        stale = await reader.get(Location, b.id)
        await LocationService(writer).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=None))
        await LocationService(writer).update_location(a.id, a.org_id, UpdateLocationRequest(parent_location_id=b.id))
        await writer.commit()
        assert stale.parent_location_id == a.id
        with pytest.raises(HTTPException) as cycle:
            await LocationService(reader).update_location(b.id, b.org_id, UpdateLocationRequest(parent_location_id=a.id))
        assert cycle.value.status_code == 400
