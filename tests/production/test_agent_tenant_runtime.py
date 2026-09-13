"""ASGI WebSocket/HTTP auth for issued device tokens on a non-owner database."""

import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
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


async def websocket(device_id, token, messages=(), *, on_send=None):
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
        if on_send is not None:
            await on_send(message)
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
async def test_auth_ack_precedes_registry_publication_and_commands(agent_runtime, credential):
    r = agent_runtime
    enrolled = await issue_device(r.world)
    token = enrolled.access_token
    if credential == "refreshed":
        result = await r.world.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
        assert result.status_code == 200
        token = result.json()["access_token"]
    elif credential == "enrollment_key":
        _, token = await issue_key(r.world)
    elif credential == "user":
        token = r.world.auth(r.world.users["org_admin"])["Authorization"].split()[1]

    async def publish_connection(ws, *_):
        # A published socket can receive work immediately from another producer.
        await ws.send_json({"type": "execute_dag", "id": "isolated-command"})
        return "runtime-session"

    r.manager.connect.side_effect = publish_connection
    for _ in range(2):
        sent = await websocket(enrolled.device_id, token)
        payloads = [json.loads(m["text"]) for m in sent if m["type"] == "websocket.send"]
        assert payloads == [
            {"type": "auth_ok", "device_id": str(enrolled.device_id), "protocol_version": 1},
            {"type": "execute_dag", "id": "isolated-command"},
        ]
        assert token not in json.dumps(payloads)


async def test_auth_ack_delivery_failure_does_not_publish_or_evict_session(agent_runtime):
    r = agent_runtime
    enrolled = await issue_device(r.world)

    async def lose_ack(message):
        if message["type"] == "websocket.send" and json.loads(message["text"]).get("type") == "auth_ok":
            raise OSError("isolated loss before auth acknowledgement delivery")

    await websocket(enrolled.device_id, enrolled.access_token, on_send=lose_ack)
    r.manager.connect.assert_not_awaited()
    r.manager.disconnect.assert_not_awaited()


@pytest.mark.parametrize("rejected", ["foreign", "invalid_token", "inactive"])
async def test_auth_ack_is_not_issued_for_rejected_identity(agent_runtime, rejected):
    r = agent_runtime
    enrolled = await issue_device(r.world)
    target, token = enrolled.device_id, enrolled.access_token
    if rejected == "foreign":
        target = r.world.dev_b.id
    elif rejected == "invalid_token":
        token = "not-a-token"
    else:
        async with r.world.sessions() as db:
            await db.execute(update(Device).where(Device.id == target).values(is_active=False))
            await db.commit()
    sent = await websocket(target, token)
    assert not [message for message in sent if message["type"] == "websocket.send"]
    r.manager.connect.assert_not_awaited()


@pytest.mark.parametrize("refresh", [False, True])
async def test_enrolled_device_discovery_uses_public_config_without_api_key_header(agent_runtime, monkeypatch, refresh):
    """APK credentials are JWTs; sending them as a config API key blocks recovery."""
    from backend.api.v1.config import router as config_router

    r = agent_runtime
    monkeypatch.setattr(config_router.settings, "AGENT_CONFIG_CACHE_TTL", 0)
    monkeypatch.setattr(config_router, "_load_agent_config_from_file", lambda: {
        "server_url": "https://discovered.invalid", "features": {"auto_register": False},
    })
    enrolled = await issue_device(r.world)
    token = enrolled.access_token
    if refresh:
        rotated = await r.world.client.post("/api/v1/devices/refresh", headers={"Cookie": "refresh_token=" + enrolled.refresh_token})
        assert rotated.status_code == 200
        token = rotated.json()["access_token"]

    rejected = await r.world.client.get("/api/v1/config/agent", headers={"X-API-Key": token})
    assert rejected.status_code == 401  # The old Android watchdog's exact request.
    public = await r.world.client.get("/api/v1/config/agent")
    assert public.status_code == 200
    assert public.json()["server_url"] == "https://discovered.invalid"
    assert public.json()["org_id"] is None
    assert public.json()["enrollment_allowed"] is False
    assert token not in public.text
    # Omitting credentials for discovery does not alter device identity or WS auth.
    sent = await websocket(enrolled.device_id, token)
    assert any(m["type"] == "websocket.send" and json.loads(m["text"]).get("type") == "auth_ok" for m in sent)


@pytest.mark.parametrize("fallback", [None, "https://secondary.invalid"])
async def test_public_discovery_advertises_optional_same_installation_fallback(agent_runtime, monkeypatch, fallback):
    from backend.api.v1.config import router as config_router

    monkeypatch.setattr(config_router.settings, "AGENT_CONFIG_CACHE_TTL", 0)
    config = {"server_url": "https://primary.invalid"}
    if fallback is not None:
        config["fallback_server_url"] = fallback
    monkeypatch.setattr(config_router, "_load_agent_config_from_file", lambda: config)
    result = await agent_runtime.world.client.get("/api/v1/config/agent")
    assert result.status_code == 200
    assert result.json()["server_url"] == "https://primary.invalid"
    assert result.json().get("fallback_server_url") == fallback
    assert result.json()["org_id"] is None


async def test_refresh_response_lost_on_primary_replays_on_secondary_origin(agent_runtime):
    """Two host names, one SQL installation; no external servers or real sockets."""
    r = agent_runtime
    enrolled = await issue_device(r.world)
    request_id = str(uuid.uuid4())
    headers = {"Cookie": "refresh_token=" + enrolled.refresh_token, "X-Refresh-Request-Id": request_id}
    committed = {}

    class LosePrimaryResponse(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            async with httpx.ASGITransport(app=app) as transport:
                response = await transport.handle_async_request(request)
                await response.aread()
                assert response.status_code == 200
                committed.update(response.json())
                await response.aclose()
            raise httpx.ReadError("isolated primary response loss after SQL commit")

    async with httpx.AsyncClient(transport=LosePrimaryResponse(), base_url="https://primary.invalid") as primary:
        with pytest.raises(httpx.ReadError):
            await primary.post("/api/v1/devices/refresh", headers=headers)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://secondary.invalid") as secondary:
        recovered = await secondary.post("/api/v1/devices/refresh", headers=headers)
        assert recovered.status_code == 200
        assert recovered.json()["refresh_token"] == committed["refresh_token"]
        assert (await secondary.post("/api/v1/devices/refresh", headers={
            **headers, "X-Refresh-Request-Id": str(uuid.uuid4()),
        })).status_code == 401
    sent = await websocket(enrolled.device_id, recovered.json()["access_token"])
    assert any(m["type"] == "websocket.send" and json.loads(m["text"]).get("device_id") == str(enrolled.device_id) for m in sent)
    foreign = await websocket(r.world.dev_b.id, recovered.json()["access_token"])
    assert not any(m["type"] == "websocket.send" for m in foreign)


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
