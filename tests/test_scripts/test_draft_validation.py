from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from backend.api.v1.scripts.router import get_script_service, router
from backend.database.engine import get_db
from backend.schemas.dag import DAGScript
from backend.services.script_service import _compute_dag_hash


def draft():
    return {"version": "1.0", "entry_node": "start", "nodes": [
        {"id": "start", "action": {"type": "start"}, "on_success": "end"},
        {"id": "end", "action": {"type": "end"}},
    ]}


@pytest.mark.parametrize("value", [[], ["tap"], {}, {"type": "tap"}, 42, True])
def test_non_string_action_type_is_a_validation_error(value):
    graph = draft()
    graph["nodes"][0]["action"]["type"] = value
    with pytest.raises(ValidationError):
        DAGScript.model_validate(graph)


@pytest.mark.parametrize("value", [[], ["end"], {}, {"target": "end"}, 12, True, ""])
def test_condition_target_is_a_nonempty_string(value):
    graph = draft()
    graph["nodes"][0]["action"] = {"type": "condition", "code": "return true", "on_true": value, "on_false": "end"}
    with pytest.raises(ValidationError):
        DAGScript.model_validate(graph)


@pytest.mark.parametrize("value", [[], ["code"], {}, {"code": "return true"}, 12, True])
def test_lua_code_type_is_rejected_before_safety_scan(value):
    graph = draft()
    graph["nodes"][0]["action"] = {"type": "lua", "code": value}
    with pytest.raises(ValidationError):
        DAGScript.model_validate(graph)


def test_duplicate_identifiers_are_rejected_even_when_reachable():
    graph = draft()
    graph["nodes"].append({"id": "end", "action": {"type": "sleep", "ms": 1}})
    with pytest.raises(ValidationError, match="unique"):
        DAGScript.model_validate(graph)


def app_for_validation(*, denied=False, path="/scripts/validate"):
    app = FastAPI()
    app.include_router(router)
    route = next(route for route in router.routes if route.path == path)

    async def principal():
        if denied:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return SimpleNamespace(id="operator", org_id="organization")

    async def forbidden_mutation_service():
        raise AssertionError("Validation must not access mutation services or a script database session")

    app.dependency_overrides[route.dependant.dependencies[0].call] = principal
    app.dependency_overrides[get_script_service] = forbidden_mutation_service
    app.dependency_overrides[get_db] = forbidden_mutation_service
    return app


async def test_http_validation_normalizes_and_hashes_without_mutation_dependency():
    graph = draft()
    original = deepcopy(graph)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for_validation()), base_url="http://fixture") as client:
        response = await client.post("/scripts/validate", json={"dag": graph})
    assert response.status_code == 200
    body = response.json()
    normalized = DAGScript.model_validate(graph).model_dump()
    assert body == {"schema_version": 1, "dag": normalized, "dag_hash": _compute_dag_hash(normalized),
                    "node_count": 2, "action_types": ["end", "start"],
                    "scope": "structure-routes-lua-safety", "device_execution_verified": False,
                    "action_contract_version": "1.0", "action_parameters_verified": True}
    assert graph == original


@pytest.mark.parametrize("case", ["duplicate", "bad_branch", "bad_type", "unsafe_lua", "unreachable"])
async def test_http_draft_errors_are_422_without_input_or_context(case):
    graph = draft()
    if case == "duplicate":
        graph["nodes"].append(graph["nodes"][1])
    elif case == "bad_branch":
        graph["nodes"][0]["action"] = {"type": "condition", "code": "return true", "on_true": ["end"], "on_false": "end"}
    elif case == "bad_type":
        graph["nodes"][0]["action"]["type"] = ["tap"]
    elif case == "unsafe_lua":
        graph["nodes"][0]["action"] = {"type": "lua", "code": 'os.execute("PRIVATE-DRAFT-TEXT")'}
    else:
        graph["nodes"].append({"id": "orphan", "action": {"type": "end"}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for_validation()), base_url="http://fixture") as client:
        response = await client.post("/scripts/validate", json={"dag": graph})
    assert response.status_code == 422
    assert "PRIVATE-DRAFT-TEXT" not in response.text
    assert all(set(error) == {"loc", "type", "msg"} for error in response.json()["detail"])


async def test_validation_requires_the_existing_auth_boundary():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for_validation(denied=True)), base_url="http://fixture") as client:
        response = await client.post("/scripts/validate", json={"dag": draft()})
    assert response.status_code == 401


@pytest.mark.parametrize("action", [
    {"type": "tap"},
    {"type": "sleep", "ms": "PRIVATE-DURATION"},
    {"type": "set_variable", "key": "value", "value": {"PRIVATE": "VALUE"}},
    {"type": "condition", "check": "battery_above", "params": [], "on_true": "end", "on_false": "end"},
    {"type": "http_request", "url": "https://example.com", "headers": {"PRIVATE HEADER NAME": "PRIVATE-VALUE"}},
])
async def test_http_rejects_action_parameters_before_any_mutation_or_device_admission(action):
    graph = draft()
    graph["nodes"][0]["action"] = action
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for_validation()), base_url="http://fixture") as client:
        response = await client.post("/scripts/validate", json={"dag": graph})
    assert response.status_code == 422
    assert "PRIVATE" not in response.text
    assert all(set(error) == {"loc", "type", "msg"} for error in response.json()["detail"])
    assert all(error["type"].startswith("action_parameter.") for error in response.json()["detail"])


async def test_creation_and_update_share_the_same_parameter_guard_before_database_access():
    from unittest.mock import AsyncMock

    from backend.schemas.script import CreateScriptRequest, UpdateScriptRequest
    from backend.services.script_service import ScriptService

    graph = draft()
    graph["nodes"][0]["action"] = {"type": "tap"}
    service = ScriptService(AsyncMock())
    with pytest.raises(HTTPException) as created:
        await service.create_script("org", "user", CreateScriptRequest(name="Fixture", dag=graph))
    assert created.value.status_code == 422
    service.db.assert_not_called()
    service._get_script = AsyncMock()
    # Update validates after ownership/version lookup, but before append/dedup.
    existing = SimpleNamespace(is_archived=False, current_version_id=None, name="Fixture", description=None)
    service._get_script.return_value = existing
    with pytest.raises(HTTPException) as updated:
        await service.update_script("script", "org", "user", UpdateScriptRequest(name="Changed", dag=graph))
    assert updated.value.status_code == 422
    assert updated.value.detail == created.value.detail
    assert not service.db.method_calls
    assert existing.name == "Fixture"


async def test_contract_is_a_bounded_read_with_auth_and_no_database_or_device_dependencies():
    from backend.schemas.dag import VALID_ACTION_TYPES

    path = "/scripts/action-contract"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for_validation(path=path)), base_url="http://fixture") as client:
        response = await client.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert len(response.content) < 65536
    body = response.json()
    assert body["version"] == body["contract"]["version"] == "1.0"
    assert set(body["contract"]["actions"]) == VALID_ACTION_TYPES
    assert body["device_execution_verified"] is body["installed_apk_capabilities_verified"] is False
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for_validation(path=path, denied=True)), base_url="http://fixture") as client:
        assert (await client.get(path)).status_code == 401
