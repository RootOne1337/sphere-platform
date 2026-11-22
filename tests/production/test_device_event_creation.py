"""Exercise async event serialization and tenant-scoped references through HTTP."""

import uuid

import pytest


async def test_created_device_event_returns_loaded_device_and_is_readable(world):
    headers = world.auth(world.users["org_admin"])
    path = "/api/v1/device-events"
    response = await world.client.post(path, headers=headers, json={
        "device_id": str(world.dev_a.id), "event_type": "fixture.event",
    })
    assert response.status_code == 201, response.text
    event = response.json()
    assert event["device_name"] == world.dev_a.name and event["account_login"] is None
    saved = await world.client.get(f"{path}/{event['id']}", headers=headers)
    assert saved.status_code == 200 and saved.json() == event


@pytest.mark.parametrize("reference", ["device_id", "account_id", "task_id", "pipeline_run_id"])
async def test_device_event_rejects_unowned_or_missing_references(world, reference):
    headers = world.auth(world.users["org_admin"])
    body = {"device_id": str(world.dev_a.id), "event_type": "fixture.event"}
    body[reference] = str(world.dev_b.id if reference == "device_id" else uuid.uuid4())
    response = await world.client.post("/api/v1/device-events", headers=headers, json=body)
    assert response.status_code == 404, response.text
