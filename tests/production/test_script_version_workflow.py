"""Archive visibility, immutable versions and contested writes on real PostgreSQL."""
import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.database.tenant import bind_tenant_context
from backend.models.script import Script, ScriptVersion
from backend.schemas.script import UpdateScriptRequest
from backend.services.script_service import ScriptService


def changed_dag(label="changed"):
    return {"version": "1.0", "name": label, "entry_node": "start", "nodes": [
        {"id": "start", "action": {"type": "start"}, "on_success": "end"},
        {"id": "end", "action": {"type": "end"}},
    ]}


async def edit(world):
    response = await world.client.put(f"/api/v1/scripts/{world.script.id}",
        headers=world.auth(world.users["org_admin"]), json={"dag": changed_dag()})
    assert response.status_code == 200, response.text
    return response.json()


async def test_archived_catalog_preserves_history_search_and_tenant_scope(world):
    headers = world.auth(world.users["org_admin"])
    path = f"/api/v1/scripts/{world.script.id}"
    assert (await world.client.delete(path, headers=headers)).status_code == 204
    active = (await world.client.get("/api/v1/scripts", headers=headers)).json()
    assert world.script.id.hex not in str(active).replace("-", "")
    archived = (await world.client.get("/api/v1/scripts", headers=headers,
        params={"state": "archived", "query": "audit-script", "per_page": 1})).json()
    assert archived["total"] == 1
    assert archived["items"][0]["id"] == str(world.script.id)
    assert archived["items"][0]["is_archived"] is True
    assert (await world.client.get(path + "/versions", headers=headers)).json()[0]["id"] == str(world.version.id)
    page2 = (await world.client.get("/api/v1/scripts", headers=headers,
        params={"state": "all", "page": 2, "per_page": 1})).json()
    assert page2["total"] == 1 and page2["items"] == []
    foreign = await world.client.get("/api/v1/scripts", headers=world.auth(world.users["foreign"]),
        params={"state": "archived"})
    assert foreign.status_code == 200 and foreign.json()["total"] == 0


async def test_unknown_catalog_state_is_rejected(world):
    response = await world.client.get("/api/v1/scripts", headers=world.auth(world.users["viewer"]),
        params={"state": "everything"})
    assert response.status_code == 422


async def test_selected_version_is_owned_immutable_and_contains_hash(world):
    headers = world.auth(world.users["viewer"])
    path = f"/api/v1/scripts/{world.script.id}/versions/{world.version.id}"
    result = await world.client.get(path, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["script_id"] == str(world.script.id)
    assert result.json()["dag"] == world.version.dag
    assert len(result.json()["dag_hash"]) == 64
    assert (await world.client.get(path, headers=world.auth(world.users["foreign"]))).status_code == 404
    assert (await world.client.get(f"/api/v1/scripts/{world.script.id}/versions/{uuid.uuid4()}", headers=headers)).status_code == 404


@pytest.mark.parametrize("operation", ["rollback", "archive", "update"])
async def test_stale_precondition_does_not_change_current_or_archive(world, operation):
    updated = await edit(world)
    headers = world.auth(world.users["org_admin"])
    path = f"/api/v1/scripts/{world.script.id}"
    expected = str(world.version.id)
    if operation == "rollback":
        result = await world.client.post(path + f"/versions/{expected}/rollback", headers=headers,
            json={"expected_current_version_id": expected})
    elif operation == "archive":
        result = await world.client.delete(path, headers=headers, params={"expected_current_version_id": expected})
    else:
        result = await world.client.put(path, headers=headers,
            json={"name": "Must not persist", "dag": changed_dag("stale"), "expected_current_version_id": expected})
    assert result.status_code == 409, result.text
    persisted = (await world.client.get(path, headers=headers)).json()
    assert persisted["current_version_id"] == updated["current_version_id"]
    assert persisted["is_archived"] is False and persisted["name"] == "audit-script"
    assert len(persisted["versions"]) == 2


async def test_conditional_rollback_creates_new_version_and_preserves_original(world):
    updated = await edit(world)
    headers = world.auth(world.users["org_admin"])
    path = f"/api/v1/scripts/{world.script.id}"
    old = (await world.client.get(path, headers=headers)).json()["versions"]
    result = await world.client.post(path + f"/versions/{world.version.id}/rollback", headers=headers,
        json={"expected_current_version_id": updated["current_version_id"]})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["current_version_id"] not in [v["id"] for v in old]
    assert body["current_version"]["version"] == 3
    assert body["current_version"]["dag"] == world.version.dag
    assert len(body["current_version"]["dag_hash"]) == 64
    fresh = (await world.client.get(path, headers=headers)).json()
    assert fresh["current_version"]["id"] == body["current_version_id"]
    for v in old:
        assert next(entry for entry in fresh["versions"] if entry["id"] == v["id"]) == v


@pytest.mark.parametrize("operation", ["rollback", "update"])
async def test_archived_script_cannot_be_changed(world, operation):
    headers = world.auth(world.users["org_admin"])
    path = f"/api/v1/scripts/{world.script.id}"
    assert (await world.client.delete(path, headers=headers)).status_code == 204
    result = await (world.client.put(path, headers=headers, json={"dag": changed_dag()}) if operation == "update"
        else world.client.post(path + f"/versions/{world.version.id}/rollback", headers=headers))
    assert result.status_code == 409, result.text
    fresh = (await world.client.get(path, headers=headers)).json()
    assert fresh["is_archived"] is True and len(fresh["versions"]) == 1


@pytest.mark.parametrize("operation", ["rollback", "archive"])
async def test_viewer_cannot_mutate_script(world, operation):
    headers = world.auth(world.users["viewer"])
    path = f"/api/v1/scripts/{world.script.id}"
    result = await (world.client.delete(path, headers=headers) if operation == "archive"
        else world.client.post(path + f"/versions/{world.version.id}/rollback", headers=headers))
    assert result.status_code == 403


@pytest.mark.parametrize("operation", ["rollback", "archive", "update"])
async def test_all_writers_are_fenced_until_commit(world, operation):
    async with world.sessions() as holder, world.sessions() as competitor:
        await ScriptService(holder).update_script(world.script.id, world.org_a.id,
            world.users["org_admin"].id, UpdateScriptRequest(dag=changed_dag()))
        service = ScriptService(competitor)
        async def write():
            if operation == "archive":
                return await service.archive_script(world.script.id, world.org_a.id)
            if operation == "rollback":
                return await service.rollback_to_version(world.script.id, world.version.id,
                    world.org_a.id, world.users["org_admin"].id)
            return await service.update_script(world.script.id, world.org_a.id,
                world.users["org_admin"].id, UpdateScriptRequest(dag=changed_dag("competitor")))
        with pytest.raises(HTTPException) as blocked:
            await asyncio.wait_for(write(), timeout=2)
        assert blocked.value.status_code == 409
        await competitor.rollback()
        await holder.commit()
        await asyncio.wait_for(write(), timeout=2)
        await competitor.commit()
    async with world.sessions() as observer:
        versions = list(await observer.scalars(select(ScriptVersion).where(ScriptVersion.script_id == world.script.id)))
        assert sorted(v.version for v in versions) == ([1, 2] if operation == "archive" else [1, 2, 3])


async def test_stale_identity_map_cannot_override_current_version(world):
    async with world.sessions() as observer, world.sessions() as writer:
        stale = await observer.get(Script, world.script.id)
        assert stale.current_version_id == world.version.id
        await ScriptService(writer).update_script(world.script.id, world.org_a.id,
            world.users["org_admin"].id, UpdateScriptRequest(dag=changed_dag()))
        await writer.commit()
        with pytest.raises(HTTPException) as conflict:
            await ScriptService(observer).archive_script(world.script.id, world.org_a.id,
                expected_current_version_id=world.version.id)
        assert conflict.value.status_code == 409


async def test_non_owner_rls_cannot_read_foreign_version(runtime_db):
    r = runtime_db
    async with r.sessions() as db:
        await bind_tenant_context(db, str(r.world.org_b.id))
        with pytest.raises(HTTPException) as hidden:
            await ScriptService(db).get_version(r.world.script.id, r.world.version.id, r.world.org_b.id)
        assert hidden.value.status_code == 404
    async with r.sessions() as db:
        await bind_tenant_context(db, str(r.world.org_a.id))
        version = await ScriptService(db).get_version(r.world.script.id, r.world.version.id, r.world.org_a.id)
        assert version.id == r.world.version.id


async def test_rollback_pins_next_task_and_archive_preserves_existing_task(world):
    from backend.models.task import Task
    from backend.services.task_service import TaskService

    async with world.sessions() as db:
        original_task = await TaskService(db).create_task(world.script.id, world.dev_a.id, world.org_a.id)
        await db.commit()
        original_task_id = original_task.id
    updated = await edit(world)
    headers = world.auth(world.users["org_admin"])
    result = await world.client.post(f"/api/v1/scripts/{world.script.id}/versions/{world.version.id}/rollback",
        headers=headers, json={"expected_current_version_id": updated["current_version_id"]})
    assert result.status_code == 200, result.text
    latest = uuid.UUID(result.json()["current_version_id"])
    async with world.sessions() as db:
        next_task = await TaskService(db).create_task(world.script.id, world.dev_a2.id, world.org_a.id)
        assert next_task.script_version_id == latest
        await db.commit()
        next_task_id = next_task.id
    assert (await world.client.delete(f"/api/v1/scripts/{world.script.id}", headers=headers,
        params={"expected_current_version_id": str(latest)})).status_code == 204
    async with world.sessions() as db:
        original = await db.get(Task, original_task_id)
        next_run = await db.get(Task, next_task_id)
        assert original.script_version_id == world.version.id
        assert next_run.script_version_id == latest
        with pytest.raises(HTTPException) as archived:
            await TaskService(db).create_task(world.script.id, world.dev_b.id, world.org_a.id)
        assert archived.value.status_code == 404
