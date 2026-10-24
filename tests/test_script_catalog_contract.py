"""Source-free projection and catalog DTO invariants, without database effects."""

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import visitors

from backend.api.v1.scripts import router as scripts_router
from backend.core.dependencies import get_current_user
from backend.schemas.script import ScriptCatalogItem, ScriptCatalogResponse
from backend.services.script_service import (
    ScriptService,
    _compute_dag_hash,
    _compute_dag_metadata,
    _script_catalog_statement,
)


def catalog_row(**changes):
    script_id, version_id, org_id = (uuid.uuid4() for _ in range(3))
    now = datetime.now(timezone.utc)
    row = {
        "total": 1, "id": script_id, "org_id": org_id, "name": "Catalog",
        "description": None, "is_archived": False, "created_at": now, "updated_at": now,
        "current_version_id": version_id, "version_id": version_id,
        "version_script_id": script_id, "version_number": 1,
        "dag_hash": "a" * 64, "node_count": 0, "version_created_at": now,
    }
    return row | changes


def fake_database(rows):
    mappings = SimpleNamespace(all=lambda: rows)
    result = SimpleNamespace(mappings=lambda: mappings)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


def test_metadata_preserves_historical_source_without_normalizing():
    historical = {"unknown": {"z": None, "a": False}, "nodes": [
        {"id": "loop", "action": {"type": "historical", "private": "雪", "n": 0}},
    ]}
    expected = json.loads(json.dumps(historical, ensure_ascii=False))
    digest, count = _compute_dag_metadata(historical)
    assert digest == _compute_dag_hash(expected) and count == 1
    assert historical == expected
    assert _compute_dag_metadata({"nodes": []})[1] == 0
    assert _compute_dag_metadata(dict(reversed(list(historical.items())))) == (digest, count)


@pytest.mark.parametrize("source", [{}, {"nodes": None}, {"nodes": {}}, {"nodes": "private"}, []])
def test_metadata_does_not_invent_zero_for_corrupt_source(source):
    with pytest.raises(ValueError, match="nodes must be an array"):
        _compute_dag_metadata(source)


@pytest.mark.parametrize("state", ["active", "archived", "all"])
def test_catalog_statement_projects_no_dag_and_counts_the_same_filtered_tenant(state):
    org_id = uuid.uuid4()
    statement = _script_catalog_statement(org_id, "_%", 3, 25, state)
    columns = {node.name for node in visitors.iterate(statement) if hasattr(node, "name")}
    assert "dag" not in columns
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.count("FROM scripts") == 1
    assert "catalog_count AS" in sql and "catalog_page AS" in sql
    assert "scripts.org_id =" in sql and "script_versions.org_id = catalog_page.org_id" in sql
    assert "script_versions.script_id = catalog_page.id" in sql
    assert "script_versions.id = catalog_page.current_version_id" in sql or "catalog_page.current_version_id = script_versions.id" in sql
    assert "LEFT OUTER JOIN" in sql and "jsonb" not in sql.lower()
    assert "ORDER BY catalog_page.updated_at DESC, catalog_page.id" in sql
    assert statement.compile(dialect=postgresql.dialect()).params["org_id_1"] == org_id


async def test_catalog_read_uses_one_query_and_only_metadata(monkeypatch):
    row = catalog_row()
    db = fake_database([row])

    def forbidden(*args, **kwargs):
        raise AssertionError("Catalog attempted to read or hash source")

    monkeypatch.setattr("backend.services.script_service._compute_dag_hash", forbidden)
    monkeypatch.setattr(scripts_router, "_to_script_response", forbidden)
    items, total = await ScriptService(db).list_script_catalog(row["org_id"])
    assert db.execute.await_count == 1 and total == 1
    assert items[0].node_count == 0
    body = ScriptCatalogResponse(items=items, total=total, page=1, per_page=50, pages=1).model_dump()
    assert "dag" not in body["items"][0]["current_version"]
    assert set(body["items"][0]["current_version"]) == {"id", "script_id", "version", "dag_hash", "created_at"}


async def test_count_only_empty_page_retains_total():
    db = fake_database([catalog_row(id=None, total=73)])
    items, total = await ScriptService(db).list_script_catalog(uuid.uuid4(), page=9, per_page=25)
    assert items == [] and total == 73 and db.execute.await_count == 1


@pytest.mark.parametrize("changes", [
    {"version_id": None}, {"dag_hash": None, "node_count": None},
    {"dag_hash": None}, {"node_count": None}, {"dag_hash": "A" * 64},
    {"dag_hash": "a" * 63}, {"node_count": -1}, {"node_count": 1.5},
    {"node_count": True}, {"version_number": 0}, {"version_script_id": uuid.uuid4()},
    {"version_id": uuid.uuid4()},
])
async def test_unavailable_catalog_metadata_is_stable_and_never_falls_back(changes):
    db = fake_database([catalog_row(**changes)])
    with pytest.raises(HTTPException) as unavailable:
        await ScriptService(db).list_script_catalog(uuid.uuid4())
    assert unavailable.value.status_code == 503
    assert unavailable.value.detail == {"code": "script_catalog_metadata_unavailable"}
    assert unavailable.value.headers == {"Cache-Control": "no-store"}
    assert db.execute.await_count == 1


async def test_unpublished_catalog_has_three_null_fields():
    row = catalog_row(current_version_id=None, version_id=None, node_count=None)
    items, _ = await ScriptService(fake_database([row])).list_script_catalog(row["org_id"])
    assert items[0].current_version_id is items[0].current_version is items[0].node_count is None
    with pytest.raises(ValidationError):
        ScriptCatalogItem.model_validate(items[0].model_dump() | {"node_count": 0})


@pytest.fixture
def catalog_app():
    app = FastAPI()
    app.include_router(scripts_router.router, prefix="/api/v1")
    user = SimpleNamespace(id=uuid.uuid4(), org_id=uuid.uuid4(), role="viewer")
    svc = SimpleNamespace(list_script_catalog=AsyncMock(return_value=([], 0)))
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[scripts_router.get_script_service] = lambda: svc
    return app, user, svc


async def test_catalog_route_precedes_uuid_route_and_requires_only_read(catalog_app):
    app, user, svc = catalog_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/scripts/catalog")
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json() == {"catalog_schema": 1, "items": [], "total": 0, "page": 1, "per_page": 50, "pages": 0}
        svc.list_script_catalog.assert_awaited_once_with(org_id=user.org_id, query=None, page=1, per_page=50, state="active")
        user.role = "api_user"
        assert (await client.get("/api/v1/scripts/catalog")).status_code == 403
        assert svc.list_script_catalog.await_count == 1


@pytest.mark.parametrize("params", [
    {"state": "everything"}, {"page": 0}, {"per_page": 0}, {"per_page": 201},
])
async def test_catalog_invalid_query_does_not_query_service(catalog_app, params):
    app, _, svc = catalog_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/scripts/catalog", params=params)
    assert response.status_code == 422
    svc.list_script_catalog.assert_not_awaited()
