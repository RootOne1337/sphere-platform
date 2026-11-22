"""HTTP regressions for explicit clearing and invalid group ancestry."""
import uuid

from backend.models.device_group import DeviceGroup
from backend.models.organization import Organization


async def child(dm_client, parent, name="Child"):
    response = await dm_client.post("/api/v1/groups", json={
        "name": name, "parent_group_id": str(parent),
    })
    assert response.status_code == 201
    return response.json()["id"]


async def test_explicit_null_clears_parent_and_keeps_metadata(dm_client, sample_group):
    group_id = await child(dm_client, sample_group.id)
    response = await dm_client.put(f"/api/v1/groups/{group_id}", json={"parent_group_id": None})
    assert response.status_code == 200
    assert response.json()["parent_group_id"] is None
    saved = next(g for g in (await dm_client.get("/api/v1/groups")).json() if g["id"] == group_id)
    assert saved["parent_group_id"] is None
    assert saved["name"] == "Child"


async def test_omitted_parent_preserves_relationship(dm_client, sample_group):
    group_id = await child(dm_client, sample_group.id)
    response = await dm_client.put(f"/api/v1/groups/{group_id}", json={"description": "Updated"})
    assert response.status_code == 200
    assert response.json()["parent_group_id"] == str(sample_group.id)


async def test_descendant_parent_rejected_without_partial_metadata_write(dm_client, sample_group):
    middle = await child(dm_client, sample_group.id)
    leaf = await child(dm_client, middle, "Leaf")
    response = await dm_client.put(f"/api/v1/groups/{sample_group.id}", json={
        "parent_group_id": leaf, "name": "Must not change", "description": "Must not change",
    })
    assert response.status_code == 400
    saved = next(g for g in (await dm_client.get("/api/v1/groups")).json()
                 if g["id"] == str(sample_group.id))
    assert saved["parent_group_id"] is None
    assert saved["name"] == sample_group.name == "Farm A"
    assert saved["description"] == "Test farm"


async def test_foreign_parent_is_not_disclosed(dm_client, sample_group, db_session):
    org = Organization(name="Foreign", slug="foreign-group-hierarchy")
    db_session.add(org)
    await db_session.flush()
    foreign = DeviceGroup(org_id=org.id, name="Foreign parent")
    db_session.add(foreign)
    await db_session.flush()
    response = await dm_client.put(f"/api/v1/groups/{sample_group.id}", json={
        "parent_group_id": str(foreign.id),
    })
    assert response.status_code == 404
    assert response.json()["detail"] == "Parent group not found"


async def test_missing_parent_rejected(dm_client, sample_group):
    response = await dm_client.put(f"/api/v1/groups/{sample_group.id}", json={
        "parent_group_id": str(uuid.uuid4()),
    })
    assert response.status_code == 404


async def test_corrupt_ancestry_is_rejected_and_can_be_repaired(dm_client, sample_group, db_session):
    other = DeviceGroup(org_id=sample_group.org_id, name="Corrupt", parent_group_id=sample_group.id)
    db_session.add(other)
    await db_session.flush()
    sample_group.parent_group_id = other.id
    await db_session.flush()
    response = await dm_client.post("/api/v1/groups", json={
        "name": "Unsafe child", "parent_group_id": str(other.id),
    })
    assert response.status_code == 400
    response = await dm_client.put(f"/api/v1/groups/{sample_group.id}", json={"parent_group_id": None})
    assert response.status_code == 200
    assert response.json()["parent_group_id"] is None
    assert (await dm_client.post("/api/v1/groups", json={
        "name": "Safe child", "parent_group_id": str(other.id),
    })).status_code == 201


async def test_explicit_null_clears_nullable_metadata(dm_client, sample_group):
    response = await dm_client.put(f"/api/v1/groups/{sample_group.id}", json={
        "description": None, "color": None,
    })
    assert response.status_code == 200
    assert response.json()["description"] is None
    assert response.json()["color"] is None
