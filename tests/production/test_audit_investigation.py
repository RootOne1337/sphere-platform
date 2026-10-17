"""Global audit investigation and bounded CSV on actual PostgreSQL/RLS."""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event, insert

from backend.database.engine import get_db
from backend.main import app
from backend.models.audit_log import AuditLog


@pytest_asyncio.fixture
async def investigation(runtime_db):
    r = runtime_db
    w = r.world
    now = datetime(2026, 10, 2, 10, tzinfo=timezone.utc)
    rows = [{"id": uuid.uuid4(), "org_id": w.org_a.id, "user_id": w.users["org_admin"].id,
             "created_at": now - timedelta(minutes=i), "action": "put.devices", "meta": {"status": "success"}}
            for i in range(105)]
    older = {"id": uuid.uuid4(), "org_id": w.org_a.id, "user_id": None,
             "created_at": now - timedelta(days=1), "action": "literal%_target", "resource_type": "groups",
             "resource_id": "rare-resource", "ip_address": "203.0.113.42",
             "meta": {"status": "failure", "private_payload": "must-not-enter-csv"},
             "old_value": {"secret": "must-not-enter-csv"}}
    foreign = {**older, "id": uuid.uuid4(), "org_id": w.org_b.id}
    async with w.sessions() as db:
        db.add_all([AuditLog(**row) for row in [*rows, older, foreign]])
        await db.commit()

    async def request_db():
        async with r.sessions() as db:
            try:
                yield db
            except Exception:
                await db.rollback()
                raise

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = request_db
    try:
        yield r, now, older
    finally:
        app.dependency_overrides[get_db] = previous


async def get(investigation, path, params=None, role="org_admin"):
    r, _, _ = investigation
    return await r.world.client.get("/api/v1/audit/" + path, params=params, headers=r.world.auth(r.world.users[role]))


@pytest.mark.parametrize("params", [
    {"q": "rare-resource"}, {"q": "status:FAILED user:system"}, {"status": "FAILED"},
    {"action": "%_target"}, {"action": "%"}, {"resource_type": "groups"}, {"q": "203.0.113.42 action:target"},
    {"from": "2026-10-01T09:59:00Z", "to": "2026-10-01T10:01:00Z"},
])
async def test_filters_find_an_event_beyond_first_page_without_foreign_rows(investigation, params):
    response = await get(investigation, "logs", params)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 1 and [row["id"] for row in data["items"]] == [str(investigation[2]["id"])]


@pytest.mark.parametrize("params", [
    {"per_page": 0}, {"per_page": -1}, {"status": "BOGUS"}, {"q": "status:BOGUS"},
    {"from": "2026-10-02T10:00:00"}, {"from": "2026-10-02T10:00:00Z", "to": "2026-10-01T10:00:00Z"},
    {"q": "a " * 21}, {"q": "x" * 501}, {"user_id": "system"},
])
async def test_invalid_investigation_is_rejected_without_unbounded_query(investigation, params):
    response = await get(investigation, "logs", params)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("path", ["logs", "logs/export"])
async def test_export_and_search_require_real_audit_permission(investigation, path):
    denied = await get(investigation, path, role="viewer")
    assert denied.status_code == 403
    unauth = await investigation[0].world.client.get("/api/v1/audit/" + path)
    assert unauth.status_code == 401


async def test_export_uses_all_matching_rows_and_excludes_payloads(investigation):
    response = await get(investigation, "logs/export", {"status": "FAILED"})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-audit-rows"] == "1" and response.headers["x-audit-truncated"] == "false"
    assert response.headers["x-audit-limit"] == "5000"
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert len(rows) == 2 and rows[1][-1] == str(investigation[2]["id"])
    assert "must-not-enter-csv" not in response.text


async def test_export_truncates_explicitly_in_one_bounded_projection_query(investigation):
    r, now, _ = investigation
    async with r.world.sessions() as db:
        await db.execute(insert(AuditLog), [{"id": uuid.uuid4(), "org_id": r.world.org_a.id,
            "created_at": now, "action": "bulk", "meta": {"status": "success"}} for _ in range(5001)])
        await db.commit()
    statements = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if "audit_logs" in statement.lower():
            statements.append(statement.lower())

    event.listen(r.engine.sync_engine, "before_cursor_execute", observe)
    try:
        response = await get(investigation, "logs/export", {"action": "bulk"})
    finally:
        event.remove(r.engine.sync_engine, "before_cursor_execute", observe)
    assert response.status_code == 200
    assert response.headers["x-audit-truncated"] == "true" and response.headers["x-audit-rows"] == "5000"
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    ids = [row[-1] for row in rows[1:]]
    assert len(ids) == len(set(ids)) == 5000
    assert ids == sorted(ids, reverse=True), "Equal timestamps must have a deterministic UUID tie-breaker"
    assert len(statements) == 1 and "limit" in statements[0]
    assert "old_value" not in statements[0] and "new_value" not in statements[0]


async def test_export_neutralizes_spreadsheet_formulas_and_quotes(investigation):
    r, now, _ = investigation
    async with r.world.sessions() as db:
        row = AuditLog(org_id=r.world.org_a.id, created_at=now,
                       action='  =HYPERLINK("evil");\ntext', resource_type="@evil", meta={})
        db.add(row)
        await db.commit()
    response = await get(investigation, "logs/export", {"q": str(row.id)})
    assert response.status_code == 200
    values = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))[1]
    assert values[2] == "'" + row.action and values[4].startswith("'@evil")


@pytest.mark.parametrize("limit", [0, 5001])
async def test_export_limit_cannot_be_disabled_or_exceeded(investigation, limit):
    response = await get(investigation, "logs/export", {"limit": limit})
    assert response.status_code == 422


async def test_uuid_actor_filter_works_with_rls_and_page_order(investigation):
    r, _, _ = investigation
    response = await get(investigation, "logs", {"user_id": str(r.world.users["org_admin"].id), "page": 2, "per_page": 100})
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 105 and len(data["items"]) == 5
    assert all(row["org_id"] == str(r.world.org_a.id) for row in data["items"])


@pytest.mark.parametrize("raw,status", [("OK", "SUCCESS"), ("succeeded", "SUCCESS"), ("completed", "SUCCESS"),
    ("FAILED", "FAILED"), ("failure", "FAILED"), ("error", "FAILED"), ("rejected", "FAILED"),
    ("warning", "WARNING"), ("degraded", "WARNING"), ("partial", "WARNING"), (None, "UNKNOWN"), ("other", "UNKNOWN")])
async def test_status_filter_and_csv_use_the_same_normalization(investigation, raw, status):
    r, now, _ = investigation
    async with r.world.sessions() as db:
        item = AuditLog(org_id=r.world.org_a.id, created_at=now, action="normalization", meta={"status": raw})
        db.add(item)
        await db.commit()
    params = {"q": str(item.id), "status": status}
    listing = await get(investigation, "logs", params)
    exported = await get(investigation, "logs/export", params)
    assert listing.status_code == exported.status_code == 200
    assert listing.json()["total"] == 1
    values = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";"))[1]
    assert values[1] == status and values[-1] == str(item.id)
