"""Pipeline definitions: real PostgreSQL transactions, HTTP contracts and tenant fences."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.database.tenant import bind_tenant_context
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_service import PipelineService


def step(identity="start", **fields):
    return {"id": identity, "name": identity, "type": "delay", "params": {"seconds": 1},
            "on_success": None, "on_failure": None, "timeout_ms": 10000, "retries": 0, **fields}


async def seeded(world, status=None):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="workflow control", description="retained",
                            steps=[step()], input_schema={}, global_timeout_ms=30000)
        db.add(pipeline)
        await db.flush()
        if status:
            db.add(PipelineRun(org_id=world.org_a.id, pipeline_id=pipeline.id,
                               device_id=world.dev_a.id, steps_snapshot=[step()], status=status))
        await db.commit()
        return pipeline


async def read(world, pipeline):
    response = await world.client.get(f"/api/v1/pipelines/{pipeline.id}", headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("operation", ["patch", "toggle", "delete"])
async def test_stale_definition_condition_rejects_whole_write(world, operation):
    pipeline = await seeded(world)
    before = await read(world, pipeline)
    stale = (pipeline.updated_at - timedelta(seconds=1)).isoformat()
    path = f"/api/v1/pipelines/{pipeline.id}"
    headers = world.auth(world.users["org_admin"])
    if operation == "patch":
        response = await world.client.patch(path, headers=headers,
                                            json={"name": "must not win", "expected_updated_at": stale})
    elif operation == "toggle":
        response = await world.client.post(path + "/toggle", headers=headers,
                                           params={"active": False, "expected_updated_at": stale})
    else:
        response = await world.client.delete(path, headers=headers, params={"expected_updated_at": stale})
    assert response.status_code == 409, response.text
    assert await read(world, pipeline) == before


INVALID = [
    {"steps": []}, {"steps": [step(str(i)) for i in range(101)]},
    {"steps": [step(), step()]}, {"steps": [step(on_success="missing")]},
    {"steps": [step(type="unknown-handler")]}, {"steps": None},
    {"name": None}, {"input_schema": None}, {"tags": None},
    {"tags": [str(i) for i in range(21)]},
]


@pytest.mark.parametrize("fields", INVALID)
async def test_invalid_patch_is_atomic(world, fields):
    pipeline = await seeded(world)
    before = await read(world, pipeline)
    response = await world.client.patch(f"/api/v1/pipelines/{pipeline.id}", headers=world.auth(world.users["org_admin"]),
                                        json={**fields, "description": "must not leak into commit"})
    assert response.status_code == 422, response.text
    assert await read(world, pipeline) == before


async def test_description_clear_and_omission_have_distinct_meanings(world):
    pipeline = await seeded(world)
    path = f"/api/v1/pipelines/{pipeline.id}"
    headers = world.auth(world.users["org_admin"])
    baseline = await read(world, pipeline)
    changed = await world.client.patch(path, headers=headers, json={"name": "metadata edit", "expected_updated_at": baseline["updated_at"]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["description"] == "retained"
    cleared = await world.client.patch(path, headers=headers, json={"description": None, "expected_updated_at": changed.json()["updated_at"]})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["description"] is None
    assert (await read(world, pipeline))["description"] is None


@pytest.mark.parametrize("status", [PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING,
                                     PipelineRunStatus.WAITING, PipelineRunStatus.PAUSED])
async def test_runtime_definition_cannot_change_under_nonterminal_run(world, status):
    pipeline = await seeded(world, status)
    before = await read(world, pipeline)
    response = await world.client.patch(f"/api/v1/pipelines/{pipeline.id}", headers=world.auth(world.users["org_admin"]),
                                        json={"name": "must not partly save", "global_timeout_ms": 60000})
    assert response.status_code == 409, response.text
    assert await read(world, pipeline) == before


async def test_terminal_snapshot_unchanged_and_identical_steps_do_not_allocate_version(world):
    pipeline = await seeded(world, PipelineRunStatus.COMPLETED)
    path = f"/api/v1/pipelines/{pipeline.id}"
    headers = world.auth(world.users["org_admin"])
    result = await world.client.patch(path, headers=headers, json={"steps": [step("new")], "global_timeout_ms": 60000})
    assert result.status_code == 200, result.text
    assert result.json()["version"] == 2
    repeated = await world.client.patch(path, headers=headers, json={"steps": [step("new")]})
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["version"] == 2
    async with world.sessions() as db:
        run = await db.scalar(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline.id))
        assert run.steps_snapshot == [step()]


async def test_metadata_and_deactivation_leave_active_run_untouched(world):
    pipeline = await seeded(world, PipelineRunStatus.RUNNING)
    path = f"/api/v1/pipelines/{pipeline.id}"
    headers = world.auth(world.users["org_admin"])
    edited = await world.client.patch(path, headers=headers, json={"name": "safe metadata"})
    assert edited.status_code == 200, edited.text
    response = await world.client.post(path + "/toggle", headers=headers,
                                       params={"active": False, "expected_updated_at": edited.json()["updated_at"]})
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    denied = await world.client.post(path + "/run", headers=headers, json={"device_id": str(world.dev_a.id)})
    assert denied.status_code == 400
    async with world.sessions() as db:
        rows = (await db.scalars(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline.id))).all()
        assert len(rows) == 1 and rows[0].status == PipelineRunStatus.RUNNING


@pytest.mark.parametrize("admission", ["run", "run_batch"])
async def test_admission_shared_lock_fences_definition_write(world, admission):
    pipeline = await seeded(world)
    async with world.sessions() as reader, world.sessions() as writer:
        svc = PipelineService(reader)
        if admission == "run":
            await svc.run(pipeline.id, world.dev_a.id, world.org_a.id)
        else:
            await svc.run_batch(pipeline.id, world.org_a.id, world.users["org_admin"].id, device_ids=[world.dev_a.id])
        with pytest.raises(HTTPException) as conflict:
            await PipelineService(writer).update(pipeline.id, world.org_a.id, global_timeout_ms=60000)
        assert conflict.value.status_code == 409
        await reader.rollback()
    async with world.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(PipelineRun).where(PipelineRun.pipeline_id == pipeline.id)) == 0


async def test_definition_lock_blocks_admission_and_refreshes_cached_identity(world):
    pipeline = await seeded(world)
    async with world.sessions() as owner, world.sessions() as contender:
        await contender.get(Pipeline, pipeline.id)
        await PipelineService(owner).toggle(pipeline.id, world.org_a.id, False)
        with pytest.raises(HTTPException) as conflict:
            await PipelineService(contender).run(pipeline.id, world.dev_a.id, world.org_a.id)
        assert conflict.value.status_code == 409
        await owner.commit()
        with pytest.raises(HTTPException) as disabled:
            await PipelineService(contender).run(pipeline.id, world.dev_a.id, world.org_a.id)
        assert disabled.value.status_code == 400


@pytest.mark.parametrize("role", ["foreign", "viewer"])
async def test_definition_write_never_crosses_permission_or_tenant_boundary(world, role):
    pipeline = await seeded(world)
    before = await read(world, pipeline)
    response = await world.client.patch(f"/api/v1/pipelines/{pipeline.id}", headers=world.auth(world.users[role]), json={"name": "forbidden"})
    # A foreign viewer is denied by permission before tenant lookup.
    assert response.status_code == 403
    assert await read(world, pipeline) == before
    if role == "foreign":
        async with world.sessions() as db:
            with pytest.raises(HTTPException) as missing:
                await PipelineService(db).update(pipeline.id, world.org_b.id, name="forbidden")
            assert missing.value.status_code == 404


async def test_non_owner_rls_protects_locked_definition(runtime_db):
    r = runtime_db
    pipeline = await seeded(r.world)
    async with r.sessions() as db:
        await bind_tenant_context(db, str(r.world.org_b.id))
        with pytest.raises(HTTPException) as hidden:
            await PipelineService(db).toggle(pipeline.id, r.world.org_a.id, False)
        assert hidden.value.status_code == 404
    assert (await read(r.world, pipeline))["is_active"] is True


@pytest.mark.parametrize("fields", [{"steps": [step(), step()]}, {"steps": [step(on_failure="missing")]}, {"steps": [step(type="bad")]}])
async def test_create_has_same_graph_contract_as_edit(world, fields):
    response = await world.client.post("/api/v1/pipelines", headers=world.auth(world.users["org_admin"]), json={"name": "invalid create", **fields})
    assert response.status_code == 422, response.text


async def test_loop_transitions_are_allowed(world):
    response = await world.client.post("/api/v1/pipelines", headers=world.auth(world.users["org_admin"]),
                                       json={"name": "loop control", "steps": [step(on_success="start")]})
    assert response.status_code == 201, response.text
