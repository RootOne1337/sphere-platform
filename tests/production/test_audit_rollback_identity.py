"""Real auth/rollback/RLS; audit must outlive the request's ORM identity map."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from backend.database.engine import get_db
from backend.main import app
from backend.models.audit_log import AuditLog
from backend.models.device_group import DeviceGroup


@pytest.mark.parametrize("outcome", ["conflict", "cycle", "missing", "forbidden"])
async def test_rejected_request_still_records_authenticated_actor_after_rollback(runtime_db, monkeypatch, outcome):
    r = runtime_db
    w = r.world
    async with w.sessions() as seed:
        group = DeviceGroup(org_id=w.org_a.id, name="Rollback source")
        duplicate = DeviceGroup(org_id=w.org_a.id, name="Duplicate")
        seed.add_all([group, duplicate])
        await seed.commit()

    async def request_db():
        async with r.sessions() as db:
            try:
                yield db
            except Exception:
                await db.rollback()  # Real production get_db failure semantics, expires user attrs.
                raise

    previous = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = request_db
    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", r.sessions)
    user = w.users["viewer"] if outcome == "forbidden" else w.users["org_admin"]
    target = w.dev_b.id if outcome == "missing" else group.id
    body = {"name": duplicate.name} if outcome == "conflict" else {"parent_group_id": str(group.id)}
    try:
        with patch("backend.services.cache_service.CacheService.is_token_blacklisted", AsyncMock(return_value=False)):
            response = await w.client.put(f"/api/v1/groups/{target}", headers=w.auth(user), json=body)
        status = {"conflict": 409, "cycle": 400, "missing": 404, "forbidden": 403}[outcome]
        assert response.status_code == status, response.text
        async with w.sessions() as observer:
            rows = list(await observer.scalars(select(AuditLog).where(AuditLog.org_id == w.org_a.id)))
            assert len(rows) == 1, "Rejected authenticated mutation was lost after request rollback"
            row = rows[0]
            assert (row.user_id, row.resource_id, row.action) == (user.id, str(target), "put.groups")
            assert row.meta["http_status"] == status and row.meta["status"] == "failure"
    finally:
        app.dependency_overrides[get_db] = previous
