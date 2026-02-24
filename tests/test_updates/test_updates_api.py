# tests/test_updates/test_updates_api.py
"""
HTTP integration tests for the OTA Updates API.

Enterprise rationale
--------------------
- SSRF guard: download_url must use https:// — http:// URLs are rejected
  with 422 before the release is persisted.  Prevents SSRF attacks where an
  attacker registers an internal-network URL (e.g. http://169.254.169.254/)
  as a download target that agents then follow.
- API-key authentication for GET /updates/latest (agent-facing endpoint).
  No cookie, no JWT — agents authenticate with X-API-Key header only.
- Version comparison: latest endpoint returns update_available=false when
  the device already runs the latest version.
- Platform/flavor filtering: release for "android/enterprise" is not returned
  when device queries "android/dev".
- CRUD lifecycle: create → list → delete → list-again shows removal.
- RBAC: device:read / device:write / device:delete permissions required.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch
from sqlalchemy.ext.asyncio import AsyncSession

import backend.api.v1.updates.router as updates_module
from backend.core.security import create_access_token
from backend.database.engine import Base, get_db
from backend.database.redis_client import get_redis
from backend.main import app
from backend.models import *  # noqa: F401,F403
from backend.models.api_key import APIKey
from backend.models.organization import Organization
from backend.models.user import User


def _patch_pg_types_for_sqlite() -> None:
    from sqlalchemy import JSON, String
    from sqlalchemy.dialects.postgresql import ARRAY, JSONB

    for table in Base.metadata.tables.values():
        for column in table.columns:
            col_type = type(column.type)
            if col_type is JSONB or col_type.__name__ == "JSONB":
                column.type = JSON()
            elif col_type.__name__ == "INET":
                column.type = String(45)
            elif col_type is ARRAY or col_type.__name__ == "ARRAY":
                column.type = JSON()


_patch_pg_types_for_sqlite()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def updates_org(db_session: AsyncSession):
    org = Organization(name="Updates Org", slug="updates-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def updates_admin(db_session: AsyncSession, updates_org):
    user = User(
        org_id=updates_org.id,
        email="updates-admin@sphere.local",
        password_hash="$2b$12$placeholder",
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def updates_viewer(db_session: AsyncSession, updates_org):
    user = User(
        org_id=updates_org.id,
        email="updates-viewer@sphere.local",
        password_hash="$2b$12$placeholder",
        role="viewer",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def agent_api_key(db_session: AsyncSession, updates_org):
    """A real API key row in the DB (type=agent) for /latest auth tests."""
    import hashlib
    raw = "sphr_test_agentkey123456789abcdef"
    api_key = APIKey(
        org_id=updates_org.id,
        name="Test Agent Key",
        key_hash=hashlib.sha256(raw.encode()).hexdigest(),
        key_prefix="sphr_test",
        type="agent",
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()
    return raw  # return plain key for use in X-API-Key header


def _make_client(db_session, mock_redis, user, org):
    token, _jti = create_access_token(
        subject=str(user.id), org_id=str(org.id), role=user.role
    )

    async def _db():
        yield db_session

    async def _redis():
        return mock_redis

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _redis

    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest_asyncio.fixture
async def admin_client(db_session, mock_redis, updates_admin, updates_org):
    async def _fake_redis():
        return mock_redis
    with patch("backend.services.cache_service.get_redis", _fake_redis):
        async with _make_client(db_session, mock_redis, updates_admin, updates_org) as c:
            yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def viewer_client(db_session, mock_redis, updates_viewer, updates_org):
    async def _fake_redis():
        return mock_redis
    with patch("backend.services.cache_service.get_redis", _fake_redis):
        async with _make_client(db_session, mock_redis, updates_viewer, updates_org) as c:
            yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def anon_client(db_session, mock_redis):
    """Unauthenticated client for agent X-API-Key tests, with proper Redis patch."""
    async def _db():
        yield db_session

    async def _fake_redis():
        return mock_redis

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_redis] = _fake_redis
    with patch("backend.services.cache_service.get_redis", _fake_redis):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def isolate_updates_file(tmp_path, monkeypatch):
    """Redirect all release storage to a per-test temp file."""
    from pathlib import Path
    test_path = tmp_path / "test_updates.json"
    monkeypatch.setattr(updates_module, "_UPDATES_PATH", test_path)
    yield test_path


_VALID_RELEASE = {
    "platform": "android",
    "flavor": "enterprise",
    "version_code": 42,
    "version_name": "1.0.42",
    "download_url": "https://cdn.example.com/sphere-1.0.42.apk",
    "sha256": "a" * 64,
    "mandatory": False,
    "changelog": "Bug fixes",
}


# ===========================================================================
# SSRF Guard — most security-critical test
# ===========================================================================

class TestSSRFGuard:
    async def test_http_url_rejected_at_creation(self, admin_client):
        """HTTP download URL must be rejected before persisting to disk."""
        payload = {**_VALID_RELEASE, "download_url": "http://192.168.1.100/evil.apk"}
        resp = await admin_client.post("/api/v1/updates/", json=payload)
        assert resp.status_code == 422
        assert "HTTPS" in resp.json()["detail"]

    async def test_internal_ip_http_url_rejected(self, admin_client):
        """SSRF via IMDS endpoint must be blocked."""
        payload = {**_VALID_RELEASE, "download_url": "http://169.254.169.254/latest/meta-data/"}
        resp = await admin_client.post("/api/v1/updates/", json=payload)
        assert resp.status_code == 422

    async def test_file_scheme_rejected(self, admin_client):
        """file:// scheme must also be rejected."""
        payload = {**_VALID_RELEASE, "download_url": "file:///etc/passwd"}
        resp = await admin_client.post("/api/v1/updates/", json=payload)
        assert resp.status_code == 422

    async def test_https_url_accepted(self, admin_client):
        """HTTPS URL is the only valid scheme."""
        resp = await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        assert resp.status_code == 201


# ===========================================================================
# GET /updates/latest — agent-facing, X-API-Key auth
# ===========================================================================

class TestGetLatest:
    async def test_no_api_key_returns_401(self, anon_client):
        resp = await anon_client.get("/api/v1/updates/latest")
        assert resp.status_code == 401

    async def test_invalid_api_key_returns_401(self, anon_client):
        resp = await anon_client.get(
            "/api/v1/updates/latest",
            headers={"X-API-Key": "sphr_test_invalid999"},
        )
        assert resp.status_code == 401

    async def test_no_releases_returns_update_available_false(
        self, anon_client, agent_api_key
    ):
        resp = await anon_client.get(
            "/api/v1/updates/latest",
            headers={"X-API-Key": agent_api_key},
        )
        assert resp.status_code == 200
        assert resp.json()["update_available"] is False

    async def test_update_available_when_newer_version_exists(
        self, admin_client, anon_client, agent_api_key
    ):
        await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        resp = await anon_client.get(
            "/api/v1/updates/latest?version_code=10",
            headers={"X-API-Key": agent_api_key},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["update_available"] is True
        assert data["version_code"] == 42
        assert data["download_url"] == _VALID_RELEASE["download_url"]

    async def test_no_update_when_device_already_at_latest(
        self, admin_client, anon_client, agent_api_key
    ):
        await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        resp = await anon_client.get(
            "/api/v1/updates/latest?version_code=42",
            headers={"X-API-Key": agent_api_key},
        )
        assert resp.status_code == 200
        assert resp.json()["update_available"] is False

    async def test_platform_flavor_filter(
        self, admin_client, anon_client, agent_api_key
    ):
        """Release for enterprise flavor must not appear when agent queries dev."""
        await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)  # enterprise
        resp = await anon_client.get(
            "/api/v1/updates/latest?platform=android&flavor=dev",
            headers={"X-API-Key": agent_api_key},
        )
        assert resp.json()["update_available"] is False


# ===========================================================================
# Admin CRUD
# ===========================================================================

class TestReleaseCRUD:
    async def test_create_release_returns_201_with_id(self, admin_client):
        resp = await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        assert resp.status_code == 201
        assert "id" in resp.json()
        assert resp.json()["version_code"] == 42

    async def test_list_releases(self, admin_client):
        await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        resp = await admin_client.get("/api/v1/updates/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] >= 1
        assert any(r["version_code"] == 42 for r in body["releases"])

    async def test_list_filter_by_platform(self, admin_client):
        await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        # Add a PC release
        pc_release = {
            **_VALID_RELEASE,
            "platform": "windows",
            "version_code": 7,
            "version_name": "1.0.7",
        }
        await admin_client.post("/api/v1/updates/", json=pc_release)

        resp = await admin_client.get("/api/v1/updates/?platform=android")
        assert resp.status_code == 200
        for r in resp.json()["releases"]:
            assert r["platform"] == "android"

    async def test_delete_release(self, admin_client):
        create_resp = await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        release_id = create_resp.json()["id"]

        del_resp = await admin_client.delete(f"/api/v1/updates/{release_id}")
        assert del_resp.status_code == 204

        # Verify gone
        list_resp = await admin_client.get("/api/v1/updates/")
        ids = [r["id"] for r in list_resp.json()["releases"]]
        assert release_id not in ids

    async def test_delete_nonexistent_returns_404(self, admin_client):
        import uuid
        resp = await admin_client.delete(f"/api/v1/updates/{uuid.uuid4()}")
        assert resp.status_code == 404

    async def test_viewer_cannot_create_release(self, viewer_client):
        resp = await viewer_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        assert resp.status_code == 403

    async def test_viewer_cannot_delete_release(self, admin_client, viewer_client):
        create_resp = await admin_client.post("/api/v1/updates/", json=_VALID_RELEASE)
        release_id = create_resp.json()["id"]

        resp = await viewer_client.delete(f"/api/v1/updates/{release_id}")
        assert resp.status_code == 403

    async def test_multiple_versions_latest_wins(
        self, admin_client, anon_client, agent_api_key
    ):
        """When multiple releases exist, the highest version_code is returned."""
        for vc in [10, 20, 42]:
            await admin_client.post(
                "/api/v1/updates/",
                json={**_VALID_RELEASE, "version_code": vc, "version_name": f"1.0.{vc}"},
            )

        resp = await anon_client.get(
            "/api/v1/updates/latest?version_code=5",
            headers={"X-API-Key": agent_api_key},
        )
        assert resp.json()["version_code"] == 42
