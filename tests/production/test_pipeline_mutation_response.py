"""Committed pipeline controls must return their fresh server timestamps."""

import pytest

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus


@pytest.mark.parametrize("operation", ["pause", "resume", "cancel", "update", "toggle"])
async def test_pipeline_mutation_response_matches_committed_state(world, operation):
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="response regression")
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(org_id=world.org_a.id, pipeline_id=pipeline.id,
                          device_id=world.dev_a.id, steps_snapshot=[],
                          status=PipelineRunStatus.PAUSED if operation == "resume" else PipelineRunStatus.RUNNING)
        db.add(run)
        await db.commit()
    headers = world.auth(world.users["org_admin"])
    if operation in {"pause", "resume", "cancel"}:
        path = f"/api/v1/pipelines/runs/{run.id}"
        response = await world.client.post(path + "/" + operation, headers=headers)
        field, value = "status", {"pause": "paused", "resume": "queued", "cancel": "cancelled"}[operation]
    else:
        path = f"/api/v1/pipelines/{pipeline.id}"
        if operation == "update":
            response = await world.client.patch(path, headers=headers, json={"name": "updated name"})
            field, value = "name", "updated name"
        else:
            response = await world.client.post(path + "/toggle", params={"active": False}, headers=headers)
            field, value = "is_active", False
    assert response.status_code == 200, response.text
    assert response.json()[field] == value
    persisted = await world.client.get(path, headers=headers)
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()[field] == value
    assert persisted.json()["updated_at"] == response.json()["updated_at"]
