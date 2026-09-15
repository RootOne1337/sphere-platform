"""Runtime invariants on disposable PostgreSQL and Redis (opt-in)."""

import importlib
from unittest.mock import patch


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
    from backend.core.security import create_access_token

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
