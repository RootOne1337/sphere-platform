"""ASGI WebSocket/HTTP auth for issued device tokens on a non-owner database."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text, update
from test_device_bootstrap_runtime import issue_device, issue_key

from backend.database.engine import get_db
from backend.main import app
from backend.models import Device


@pytest.fixture
def agent_runtime(runtime_db, monkeypatch, tmp_path):
    async def request_db():
        async with runtime_db.sessions() as db:
            yield db
    app.dependency_overrides[get_db] = request_db
    monkeypatch.setattr("backend.api.ws.android.router.AsyncSessionLocal", runtime_db.sessions)
    monkeypatch.setattr("backend.api.ws.android.router.get_redis_binary", AsyncMock(return_value=runtime_db.world.redis))
    manager = SimpleNamespace(connect=AsyncMock(return_value="runtime-session"), disconnect=AsyncMock(return_value=False))
    monkeypatch.setattr("backend.api.ws.android.router.get_connection_manager", lambda: manager)
    monkeypatch.setattr("backend.api.ws.android.router.DeviceStatusCache", lambda _: SimpleNamespace(set_status=AsyncMock()))
    monkeypatch.setattr("backend.websocket.heartbeat.HeartbeatManager", lambda *args, **kwargs: SimpleNamespace(start=AsyncMock(), stop=AsyncMock()))
    # No delivery side effects or listeners; the actual ASGI router and SQL auth run.
    for module, factory in [("pubsub_router", "get_pubsub_router"), ("event_publisher", "get_event_publisher"), ("offline_queue", "get_offline_queue"), ("stream_bridge", "get_stream_bridge")]:
        monkeypatch.setattr(f"backend.websocket.{module}.{factory}", lambda: None)
    monkeypatch.setattr("backend.api.v1.logs.router._LOGS_DIR", tmp_path)
    monkeypatch.setattr("backend.api.v1.updates.router._UPDATES_PATH", tmp_path / "updates.json")
    return SimpleNamespace(db=runtime_db, world=runtime_db.world, manager=manager, path=tmp_path)


async def websocket(device_id, token, messages=()):
    events = iter([
        {"type": "websocket.connect"},
        {"type": "websocket.receive", "text": json.dumps({"token": token})},
        *({"type": "websocket.receive", "text": json.dumps(message)} for message in messages),
        {"type": "websocket.disconnect", "code": 1000},
    ])
    sent = []

    async def receive():
        return next(events)

    async def send(message):
        sent.append(message)

    path = f"/ws/android/{device_id}"
    await asyncio.wait_for(app({
        "type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "ws", "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"host", b"audit.local")], "client": ("127.0.0.1", 12345),
        "server": ("audit.local", 80), "root_path": "", "subprotocols": [],
    }, receive, send), 5)
    return sent


@pytest.mark.parametrize("credential", ["device", "refreshed", "enrollment_key", "user"])
async def test_runtime_agent_websocket_connect_and_reconnect(agent_runtime, credential):
    r = agent_runtime
    enrolled = await issue_device(r.world)
    token = enrolled.access_token
    if credential == "refreshed":
        response = await r.world.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
        assert response.status_code == 200
        token = response.json()["access_token"]
    elif credential == "enrollment_key":
        _, token = await issue_key(r.world)
    elif credential == "user":
        token = r.world.auth(r.world.users["org_admin"])["Authorization"].split()[1]
    for attempt in range(2):
        sent = await websocket(enrolled.device_id, token)
        assert r.manager.connect.await_count == attempt + 1, sent
        assert r.manager.connect.call_args.args[1:] == (str(enrolled.device_id), "android", str(r.world.org_a.id))
        assert r.manager.disconnect.await_count == attempt + 1
        assert not [m for m in sent if m["type"] == "websocket.close"]
    async with r.db.sessions() as fresh:
        assert await fresh.scalar(text("SELECT count(*) FROM devices")) == 0


@pytest.mark.parametrize("target", ["own", "same_org_other", "foreign"])
async def test_runtime_agent_http_device_scope(agent_runtime, target):
    r = agent_runtime
    enrolled = await issue_device(r.world)
    device_id = {"own": enrolled.device_id, "same_org_other": r.world.dev_a2.id, "foreign": r.world.dev_b.id}[target]
    response = await r.world.client.post("/api/v1/logs/upload", headers={
        "X-API-Key": enrolled.access_token, "X-Device-Id": str(device_id),
    }, content=b"isolated-log")
    assert response.status_code == (204 if target == "own" else 404), response.text
    files = list(r.path.rglob("*.log"))
    assert len(files) == (1 if target == "own" else 0)
    if files:
        assert b"isolated-log" in files[0].read_bytes()
    ota = await r.world.client.get("/api/v1/updates/latest", headers={"X-API-Key": enrolled.access_token})
    assert ota.status_code == 200, ota.text


@pytest.mark.parametrize("rejected", ["other_device", "foreign_device", "inactive", "moved", "viewer", "revoked", "malformed"])
async def test_runtime_agent_ws_rejects_wrong_or_revoked_identity(agent_runtime, rejected):
    r = agent_runtime
    enrolled = await issue_device(r.world)
    token = enrolled.access_token
    target = enrolled.device_id
    if rejected in {"inactive", "moved"}:
        values = {"is_active": False} if rejected == "inactive" else {"org_id": r.world.org_b.id}
        async with r.world.sessions() as db:
            await db.execute(update(Device).where(Device.id == target).values(**values))
            await db.commit()
    elif rejected == "viewer":
        token = r.world.auth(r.world.users["viewer"])["Authorization"].split()[1]
    elif rejected == "revoked":
        from backend.core.security import decode_access_token
        from backend.services.cache_service import CacheService
        claims = decode_access_token(token)
        await CacheService().blacklist_token(claims["jti"], 60)
    elif rejected == "malformed":
        token = "not-a-token"
    else:
        target = r.world.dev_a2.id if rejected == "other_device" else r.world.dev_b.id
    sent = await websocket(target, token)
    r.manager.connect.assert_not_awaited()
    closes = [m for m in sent if m["type"] == "websocket.close"]
    assert len(closes) == 1 and closes[0]["code"] in {4001, 4004}, sent


async def test_runtime_full_enrollment_refresh_connection_lifecycle(agent_runtime):
    r = agent_runtime
    _, key = await issue_key(r.world)
    enrolled = await r.world.client.post("/api/v1/devices/register", headers={"X-API-Key": key}, json={"fingerprint": r.world.suffix})
    assert enrolled.status_code == 201, enrolled.text
    first = enrolled.json()
    await websocket(first["device_id"], first["access_token"])
    r.manager.connect.assert_awaited_once()
    refreshed = await r.world.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + first["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    await websocket(first["device_id"], refreshed.json()["access_token"])
    assert r.manager.connect.await_count == 2
    ota = await r.world.client.get("/api/v1/updates/latest", headers={"X-API-Key": refreshed.json()["access_token"]})
    assert ota.status_code == 200


async def test_agent_auth_sql_failure_closes_socket_and_next_session_recovers(agent_runtime, monkeypatch):
    from contextlib import asynccontextmanager

    r = agent_runtime
    enrolled = await issue_device(r.world)

    @asynccontextmanager
    async def broken_sessions():
        async with r.db.sessions() as db:
            await db.execute(text("SELECT 1/0"))
            yield db
    monkeypatch.setattr("backend.api.ws.android.router.AsyncSessionLocal", broken_sessions)
    sent = await websocket(enrolled.device_id, enrolled.access_token)
    assert [m["code"] for m in sent if m["type"] == "websocket.close"] == [1011]
    r.manager.connect.assert_not_awaited()
    monkeypatch.setattr("backend.api.ws.android.router.AsyncSessionLocal", r.db.sessions)
    await websocket(enrolled.device_id, enrolled.access_token)
    r.manager.connect.assert_awaited_once()
