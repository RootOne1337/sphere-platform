"""Runtime invariants on disposable PostgreSQL and Redis (opt-in)."""

import importlib
import os
import time
from unittest.mock import patch

from backend.core.security import create_access_token


async def test_logs_are_tenant_scoped(world, tmp_path):
    w = world
    router = importlib.import_module("backend.api.v1.logs.router")
    with patch.object(router, "_LOGS_DIR", tmp_path):
        router._get_log_file(str(w.dev_b.id)).write_text("isolated-fixture-log")
        response = await w.client.get(
            f"/api/v1/logs/{w.dev_b.id}", headers=w.auth(w.users["viewer"])
        )
        assert response.status_code == 404
        response = await w.client.delete(
            f"/api/v1/logs/{w.dev_b.id}", headers=w.auth(w.users["org_admin"])
        )
        assert response.status_code == 404
        assert "isolated-fixture-log" in router._get_log_file(str(w.dev_b.id)).read_text()


async def test_global_ota_requires_platform_authority(world, tmp_path):
    w = world
    router = importlib.import_module("backend.api.v1.updates.router")
    with patch.object(router, "_UPDATES_PATH", tmp_path / "updates.json"):
        response = await w.client.post(
            "/api/v1/updates/",
            headers=w.auth(w.users["org_admin"]),
            json={
                "version_code": 1,
                "version_name": "audit",
                "download_url": "https://example.invalid/a.apk",
                "sha256": "0" * 64,
            },
        )
        assert response.status_code == 403
        assert not router._UPDATES_PATH.exists()


async def test_device_jwt_is_accepted_by_agent_http_endpoints(world, tmp_path):
    w = world
    token, _ = create_access_token(subject=str(w.dev_a.id), org_id=str(w.org_a.id), role="device")
    router = importlib.import_module("backend.api.v1.logs.router")
    with patch.object(router, "_LOGS_DIR", tmp_path):
        response = await w.client.post(
            "/api/v1/logs/upload",
            headers={"X-API-Key": token, "X-Device-Id": str(w.dev_a.id)},
            content=b"fixture",
        )
        assert response.status_code == 204, response.text
        response = await w.client.post(
            f"/api/v1/logs/upload?device_id={w.dev_a2.id}",
            headers={"X-API-Key": token},
            content=b"fixture",
        )
        assert response.status_code == 404
    response = await w.client.get("/api/v1/updates/latest", headers={"X-API-Key": token})
    assert response.status_code == 200, response.text


async def test_log_organization_quota_includes_retired_legacy_journal(runtime_db, tmp_path, monkeypatch):
    from backend.database.engine import get_db
    from backend.main import app
    from backend.models.device import Device
    from backend.services.device_log_storage import SWEEP_MARKER, sweep_device_journals

    world = runtime_db.world
    router = importlib.import_module("backend.api.v1.logs.router")
    monkeypatch.setattr(router, "_LOGS_DIR", tmp_path)
    monkeypatch.setattr(router.settings, "DEVICE_LOG_ORG_MAX_BYTES", 250)

    async with world.sessions() as db:
        retired = await db.get(Device, world.dev_a2.id)
        retired.is_active = False
        await db.commit()

    legacy = router._get_log_file(str(world.dev_a2.id))
    legacy.write_bytes(b"retained legacy journal" * 10)
    foreign = router._get_log_file(str(world.dev_b.id))
    foreign.write_bytes(b"foreign journal" * 5)

    async def runtime_sessions():
        async with runtime_db.sessions() as db:
            yield db

    def auth(device):
        token, _ = create_access_token(subject=str(device.id), org_id=str(device.org_id), role="device")
        return {"X-API-Key": token, "X-Device-Id": str(device.id)}

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = runtime_sessions
    try:
        upload = "/api/v1/logs/upload"
        denied = await world.client.post(upload, headers=auth(world.dev_a), content=b"new journal")
        assert denied.status_code == 507 and denied.headers["Retry-After"] == "900", denied.text
        assert not router._get_log_file(str(world.dev_a.id), create_directory=False).exists()
        assert legacy.read_bytes() == b"retained legacy journal" * 10
        allowed = await world.client.post(upload, headers=auth(world.dev_b), content=b"another organization")
        assert allowed.status_code == 204, allowed.text
        assert foreign.read_bytes().startswith(b"foreign journal" * 5)

        stale = time.time() - 31 * 86400
        for path in legacy, tmp_path / SWEEP_MARKER:
            os.utime(path, (stale, stale))
        sweep_device_journals(tmp_path)
        assert not legacy.exists()
        recovered = await world.client.post(upload, headers=auth(world.dev_a), content=b"new journal")
        assert recovered.status_code == 204, recovered.text
        response = await world.client.get(
            f"/api/v1/logs/{world.dev_a.id}", headers=world.auth(world.users["viewer"]),
        )
        assert response.status_code == 200 and "new journal" in response.text
    finally:
        app.dependency_overrides[get_db] = original
