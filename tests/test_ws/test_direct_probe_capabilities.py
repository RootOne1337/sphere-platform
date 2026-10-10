"""Real HTTP admission/auth boundaries, without Redis peers or network traffic."""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from backend.api.v1.direct_probe import router
from backend.core.dependencies import get_current_user
from backend.database.engine import get_db

DEVICE = uuid.UUID("753fd530-2f19-4e5e-98ba-769863678141")
ORG = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
URL = f"/devices/{DEVICE}/direct-probe-capabilities"


@pytest_asyncio.fixture
async def admission(monkeypatch):
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=DEVICE, org_id=ORG, is_active=True)
    user = SimpleNamespace(id=uuid.uuid4(), org_id=ORG, role="viewer")
    runtime = SimpleNamespace(available=True, prepare=AsyncMock())
    monkeypatch.setattr(router, "bind_tenant_context", AsyncMock())
    monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: runtime)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", True)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED", False)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED", False)
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({str(DEVICE)}))
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_URLS", ())
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_SECRET", SecretStr(""))

    async def database():
        yield db

    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield app, client, db, user, runtime
    runtime.prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_allowed_read_is_private_finite_and_never_allocates_peer(admission):
    _, client, db, _, _ = admission
    response = await client.get(URL)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == dict(schema_version=1, device_id=str(DEVICE), enabled=True,
                                   profiles=["host", "public-stun"], scope="diagnostic_echo_only",
                                   max_duration_ms=30000, samples=20, readonly_video_enabled=False, live_video_enabled=False)
    db.get.assert_awaited_once_with(router.Device, DEVICE)
    router.bind_tenant_context.assert_awaited_once_with(db, str(ORG))


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["disabled", "other_device", "runtime", "no_runtime"])
async def test_configuration_or_worker_denial_does_not_advertise_a_profile(admission, monkeypatch, denial):
    _, client, _, _, runtime = admission
    if denial == "disabled":
        monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_ENABLED", False)
    elif denial == "other_device":
        monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_PROBE_DEVICE_IDS", frozenset({str(uuid.uuid4())}))
    elif denial == "runtime":
        runtime.available = False
    else:
        monkeypatch.setattr(router, "get_direct_probe_runtime", lambda: None)
    response = await client.get(URL)
    assert response.status_code == 200
    assert response.json()["enabled"] is False and response.json()["profiles"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("version,online,allowed", [(10250, True, False), (None, True, False), (10251, False, False), (10251, True, True)])
async def test_readonly_video_requires_separate_admission_and_fresh_native_version(admission, monkeypatch, version, online, allowed):
    _, client, _, _, runtime = admission
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED", True)
    status = SimpleNamespace(agent_version_code=version, ws_session_id="fresh", status="online" if online else "offline")
    cache = SimpleNamespace(get_status=AsyncMock(return_value=status))
    runtime.redis = object()
    monkeypatch.setattr(router, "DeviceStatusCache", lambda redis: cache)
    response = await client.get(URL)
    assert response.status_code == 200
    assert response.json()["readonly_video_enabled"] is allowed
    assert response.json()["scope"] == "diagnostic_echo_only"
    runtime.prepare.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("version,online,allowed", [(10251, True, False), (None, True, False), (10252, False, False), (10252, True, True)])
async def test_primary_video_requires_its_own_native_version_and_never_allocates_a_peer(admission, monkeypatch, version, online, allowed):
    _, client, _, _, runtime = admission
    monkeypatch.setattr(router.settings, "DIRECT_TRANSPORT_LIVE_VIDEO_ENABLED", True)
    cache = SimpleNamespace(get_status=AsyncMock(return_value=SimpleNamespace(
        agent_version_code=version, ws_session_id="fresh", status="online" if online else "offline")))
    runtime.redis = object()
    monkeypatch.setattr(router, "DeviceStatusCache", lambda redis: cache)
    response = await client.get(URL)
    assert response.status_code == 200 and response.json()["live_video_enabled"] is allowed
    assert response.json()["readonly_video_enabled"] is False
    runtime.prepare.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("denial", ["missing", "foreign", "inactive", "role", "anonymous"])
async def test_auth_tenant_and_active_device_boundaries(admission, denial):
    app, client, db, user, _ = admission
    expected = 404
    if denial == "missing":
        db.get.return_value = None
    elif denial == "foreign":
        db.get.return_value.org_id = uuid.uuid4()
    elif denial == "inactive":
        db.get.return_value.is_active = False
    elif denial == "role":
        user.role = "api_user"
        expected = 403
    else:
        del app.dependency_overrides[get_current_user]
        expected = 401
    response = await client.get(URL)
    assert response.status_code == expected
    if denial in {"role", "anonymous"}:
        db.get.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("urls,key,allowed", [
    (("turn:relay.example.com:3478?transport=udp",), "a" * 64, True),
    (("turn:127.0.0.1:3478?transport=udp",), "a" * 64, False),
    (("turn:relay.example.com:3478?transport=udp",), "short", False),
    (("turn:relay.example.com:3478?transport=udp",), "a" * 32 + " ", False),
])
async def test_turn_is_advertised_only_for_valid_configuration_without_keys(admission, monkeypatch, urls, key, allowed):
    _, client, _, _, _ = admission
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_URLS", urls)
    monkeypatch.setattr(router.settings, "DIRECT_PROBE_TURN_SECRET", SecretStr(key))
    response = await client.get(URL)
    assert response.status_code == 200
    assert ("turn" in response.json()["profiles"]) is allowed
    assert "credential" not in response.text and "relay.example.com" not in response.text
    assert key not in response.text


@pytest.mark.asyncio
async def test_ws_also_rejects_an_inactive_device_after_capability_read(monkeypatch):
    from backend.api.ws.direct import router as ws_router
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(org_id=ORG, is_active=False)

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(ws_router, "AsyncSessionLocal", session)
    monkeypatch.setattr(ws_router, "_authenticate_viewer", AsyncMock(return_value=SimpleNamespace(
        id=uuid.uuid4(), org_id=ORG, role="viewer")))
    with pytest.raises(HTTPException) as rejected:
        await ws_router.authorize("fixture", str(DEVICE))
    assert rejected.value.status_code == 403
