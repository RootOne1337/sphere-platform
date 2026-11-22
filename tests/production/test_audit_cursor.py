"""Cursor order, admission and compatibility under a PostgreSQL runtime role."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import event, text

from backend.database.engine import get_db
from backend.main import app
from backend.models.audit_log import AuditLog
from backend.models.user import User

CURSOR_PATH = "/api/v1/audit/logs/cursor"
NOW = datetime(2026, 11, 14, 1, tzinfo=timezone.utc)
IDS = [uuid.UUID(int=value) for value in range(1, 8)]


@pytest_asyncio.fixture
async def cursor_world(runtime_db):
    world = runtime_db.world
    async with world.sessions() as db:
        foreign_admin = User(org_id=world.org_b.id, email=f"audit-admin-{world.suffix}@example.org",
                             password_hash="unused-local-fixture", role="org_admin")
        db.add(foreign_admin)
        db.add_all([AuditLog(id=row_id, org_id=world.org_a.id, created_at=NOW, action="audit.cursor.fixture")
                    for row_id in [uuid.uuid5(world.org_a.id, str(fixture_id)) for fixture_id in IDS]])
        db.add(AuditLog(org_id=world.org_b.id, created_at=NOW, action="audit.cursor.foreign"))
        await db.commit()

    async def runtime_session():
        async with runtime_db.sessions() as db:
            yield db

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = runtime_session
    try:
        yield runtime_db, foreign_admin
    finally:
        app.dependency_overrides[get_db] = previous


async def list_by_cursor(cursor_world, params=None, user=None):
    runtime, _ = cursor_world
    world = runtime.world
    return await world.client.get(CURSOR_PATH, params=params, headers=world.auth(user or world.users["org_admin"]))


async def test_cursor_has_no_duplicates_or_skips_after_new_insert_and_equal_timestamps(cursor_world):
    runtime, _ = cursor_world
    world = runtime.world
    expected = sorted((str(uuid.uuid5(world.org_a.id, str(fixture_id))) for fixture_id in IDS), reverse=True)
    first = await list_by_cursor(cursor_world, {"per_page": 3})
    assert first.status_code == 200, first.text
    assert first.headers["Cache-Control"] == "private, no-store"
    entries = first.json()
    assert [row["id"] for row in entries["items"]] == expected[:3]
    assert entries["next_cursor"]

    async with world.sessions() as db:
        db.add(AuditLog(org_id=world.org_a.id, created_at=NOW + timedelta(seconds=1), action="audit.cursor.insert"))
        await db.commit()

    statements = []

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if "audit_logs" in statement.lower():
            statements.append(statement.lower())

    event.listen(runtime.engine.sync_engine, "before_cursor_execute", observe)
    try:
        second = await list_by_cursor(cursor_world, {"per_page": 3, "cursor": entries["next_cursor"]})
    finally:
        event.remove(runtime.engine.sync_engine, "before_cursor_execute", observe)
    assert second.status_code == 200, second.text
    page = second.json()
    assert [row["id"] for row in page["items"]] == expected[3:6]
    assert page["next_cursor"]
    assert len(statements) == 1
    assert "(audit_logs.created_at, audit_logs.id) <" in statements[0]
    assert "offset" not in statements[0] and "count(" not in statements[0]
    final = await list_by_cursor(cursor_world, {"per_page": 3, "cursor": page["next_cursor"]})
    assert final.status_code == 200, final.text
    assert [row["id"] for row in final.json()["items"]] == expected[6:]
    assert final.json()["next_cursor"] is None

    async with world.sessions() as db:
        await db.execute(text("SET LOCAL enable_seqscan = off"))
        plan = (await db.execute(text("""EXPLAIN SELECT id FROM audit_logs
             WHERE org_id = :org AND (created_at, id) < (:created_at, :id)
             ORDER BY created_at DESC, id DESC LIMIT 4"""),
             {"org": world.org_a.id, "created_at": NOW, "id": uuid.UUID(expected[2])})).scalars().all()
    assert any("Index Only Scan Backward using ix_audit_logs_org_created_id" in node for node in plan)


async def test_cursor_rejects_malformed_tampered_foreign_and_query_changed_tokens(cursor_world):
    runtime, foreign_admin = cursor_world
    world = runtime.world
    params = {"per_page": 2, "q": "action:cursor", "from": "2026-11-14T01:00:00Z"}
    first = await list_by_cursor(cursor_world, params)
    assert first.status_code == 200, first.text
    token = first.json()["next_cursor"]
    assert isinstance(token, str)
    tampered = token[:-1] + ("a" if token[-1] == "b" else "b")
    for change in ({"cursor": "bad"}, {"cursor": "x" * 513}, {"cursor": tampered}, {"q": "audit"}, {"per_page": 3}):
        bad = await list_by_cursor(cursor_world, params | {"cursor": token} | change)
        assert bad.status_code == 422
    foreign = await list_by_cursor(cursor_world, params | {"cursor": token}, user=foreign_admin)
    assert foreign.status_code == 422
    viewer = await list_by_cursor(cursor_world, params | {"cursor": token}, user=world.users["viewer"])
    assert viewer.status_code == 403
    equivalent_offset = await list_by_cursor(cursor_world, params | {"cursor": token, "from": "2026-11-14T06:00:00+05:00"})
    assert equivalent_offset.status_code == 200

    legacy = await world.client.get("/api/v1/audit/logs", params={"page": 2, "per_page": 2},
                                    headers=world.auth(world.users["org_admin"]))
    assert legacy.status_code == 200
    assert legacy.json().keys() == {"items", "total", "page", "per_page", "pages"}
