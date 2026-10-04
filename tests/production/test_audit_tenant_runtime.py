"""The actual ASGI audit background writer must use its own tenant-bound Session."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select, text

from backend.models import AuditLog


async def logs_for_world(world):
    async with world.sessions() as db:
        return list((await db.scalars(select(AuditLog).where(AuditLog.org_id.in_([world.org_a.id, world.org_b.id])))).all())


@pytest.mark.parametrize("outcome", ["success", "forbidden", "not_found"])
async def test_asgi_audit_write_uses_runtime_role_and_captured_tenant(runtime_db, monkeypatch, outcome):
    w = runtime_db.world
    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", runtime_db.sessions)
    user = w.users["viewer"] if outcome == "forbidden" else w.users["org_admin"]
    device = w.dev_b if outcome == "not_found" else w.dev_a
    response = await w.client.put(f"/api/v1/devices/{device.id}", headers=w.auth(user), json={"name": "audit-runtime"})
    status = {"success": 200, "forbidden": 403, "not_found": 404}[outcome]
    assert response.status_code == status, response.text
    rows = await logs_for_world(w)
    assert len(rows) == 1
    row = rows[0]
    assert (row.org_id, row.user_id, row.resource_id, row.action) == (w.org_a.id, user.id, str(device.id), "put.devices")
    assert row.meta["http_status"] == status
    assert row.meta["status"] == ("success" if status == 200 else "failure")


async def test_concurrent_tenant_audits_do_not_share_context_on_one_connection(runtime_db, monkeypatch):
    w = runtime_db.world
    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", runtime_db.sessions)
    first, second = await asyncio.gather(
        w.client.put(f"/api/v1/devices/{w.dev_a.id}", headers=w.auth(w.users["org_admin"]), json={"name": "audit-A"}),
        w.client.put(f"/api/v1/devices/{w.dev_b.id}", headers=w.auth(w.users["foreign"]), json={"name": "audit-B"}),
    )
    assert (first.status_code, second.status_code) == (200, 403)
    rows = await logs_for_world(w)
    assert {(r.org_id, r.user_id, r.resource_id, r.meta["http_status"]) for r in rows} == {
        (w.org_a.id, w.users["org_admin"].id, str(w.dev_a.id), 200),
        (w.org_b.id, w.users["foreign"].id, str(w.dev_b.id), 403),
    }
    async with runtime_db.sessions() as fresh:
        assert await fresh.scalar(text("SELECT current_setting('app.current_org_id', true)")) in (None, "")
        assert await fresh.scalar(text("SELECT count(*) FROM audit_logs")) == 0


async def test_audit_sql_failure_is_reported_and_next_tenant_writer_recovers(runtime_db, monkeypatch):
    w = runtime_db.world
    attempts = 0

    @asynccontextmanager
    async def faulting_sessions():
        nonlocal attempts
        attempts += 1
        async with runtime_db.sessions() as db:
            if attempts == 1:
                async def fail_commit():
                    await db.flush()  # The audit INSERT must reach PostgreSQL successfully first.
                    await db.execute(text("SELECT 1/0"))
                with patch.object(db, "commit", fail_commit):
                    yield db
            else:
                yield db

    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", faulting_sessions)
    with patch("backend.middleware.audit.logger.error") as error:
        first = await w.client.put(f"/api/v1/devices/{w.dev_a.id}", headers=w.auth(w.users["org_admin"]), json={"name": "audit-fault"})
        assert first.status_code == 200
        assert await logs_for_world(w) == []
        error.assert_called_once()
        assert error.call_args.args == ("audit_log_write_failed",)
        assert "division by zero" in error.call_args.kwargs["error"]
        second = await w.client.put(f"/api/v1/devices/{w.dev_b.id}", headers=w.auth(w.users["foreign"]), json={"name": "audit-next"})
        assert second.status_code == 403
        rows = await logs_for_world(w)
        assert len(rows) == 1
        assert rows[0].org_id == w.org_b.id
        assert error.call_count == 1
    # This intentionally documents the remaining durability gap after HTTP commit:
    # the failed first audit is not retried. A durable outbox is a separate fix.


async def test_unauthenticated_request_does_not_create_a_tenant_audit(runtime_db, monkeypatch):
    w = runtime_db.world
    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", runtime_db.sessions)
    response = await w.client.put(f"/api/v1/devices/{w.dev_a.id}", json={"name": "unauthenticated"})
    assert response.status_code == 401
    assert await logs_for_world(w) == []
