"""Real PostgreSQL mutations must serialize their committed current version."""

import pytest


@pytest.mark.parametrize("operation", ["create", "update", "rollback"])
async def test_committed_script_response_contains_current_version(world, operation):
    dag = {
        "version": "1.0", "entry_node": "start",
        "nodes": [
            {"id": "start", "action": {"type": "start"}, "on_success": "end"},
            {"id": "end", "action": {"type": "end"}},
        ],
    }
    headers = world.auth(world.users["org_admin"])
    if operation == "create":
        response = await world.client.post("/api/v1/scripts", headers=headers,
            json={"name": "mutation response regression", "dag": dag})
        expected_status, expected_version = 201, 1
    elif operation == "update":
        response = await world.client.put(f"/api/v1/scripts/{world.script.id}",
            headers=headers, json={"dag": dag})
        expected_status, expected_version = 200, 2
    else:
        response = await world.client.post(
            f"/api/v1/scripts/{world.script.id}/versions/{world.version.id}/rollback",
            headers=headers)
        expected_status, expected_version = 200, 2
    assert response.status_code == expected_status, response.text
    body = response.json()
    assert body["current_version"]["id"] == body["current_version_id"]
    assert body["current_version"]["version"] == expected_version
    # A fresh HTTP/DB session must report exactly the same durable version.
    persisted = await world.client.get(f"/api/v1/scripts/{body['id']}", headers=headers)
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["current_version"]["id"] == body["current_version_id"]
    assert persisted.json()["current_version"]["dag"] == body["current_version"]["dag"]
