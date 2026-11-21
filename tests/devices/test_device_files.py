import base64
import hashlib
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from backend.api.v1.device_files import router as file_routes
from backend.core.dependencies import get_current_user
from backend.database.redis_client import get_redis_binary
from backend.main import app
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache


@pytest.fixture
async def exchange(authenticated_client, test_device, test_user, monkeypatch):
    redis = FakeRedis()
    test_user.role = "device_manager"
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_redis_binary] = lambda: redis
    rpc = AsyncMock()
    monkeypatch.setattr(file_routes, "get_pubsub_publisher", lambda: rpc)
    cache = DeviceStatusCache(redis)
    device_id = str(test_device.id)

    async def report(version=1, state="online"):
        await cache.set_status(device_id, DeviceLiveStatus(
            device_id=device_id, ws_session_id="test-session", last_heartbeat=datetime.now(timezone.utc),
            status=state, file_exchange_version=version,
        ))

    await report()
    try:
        yield authenticated_client, f"/api/v1/devices/{device_id}/files", rpc, report, test_user
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_redis_binary, None)
        await redis.aclose()


def binary_headers(content):
    return {"Content-Type": "application/octet-stream", "X-Content-SHA256": hashlib.sha256(content).hexdigest()}


async def test_list_write_and_download_validated_and_session_fenced(exchange):
    client, url, rpc, _, _ = exchange
    data = b"Sphere file exchange\x00\xff"
    headers = binary_headers(data)
    receipt = {"name": "canary.txt", "size": len(data), "sha256": headers["X-Content-SHA256"]}
    rpc.send_command_wait_result.side_effect = [
        {"status": "completed", "result": {"version": 1, "max_bytes": 262144, "files": []}},
        {"status": "completed", "result": receipt},
        {"status": "completed", "result": receipt | {"data": base64.b64encode(data).decode()}},
    ]
    listed = await client.get(url)
    assert listed.status_code == 200 and listed.json()["files"] == []
    written = await client.post(f"{url}/canary.txt", headers=headers, content=data)
    assert written.status_code == 201 and written.json() == receipt
    read = await client.get(f"{url}/canary.txt")
    assert read.status_code == 200 and read.content == data
    assert read.headers["X-Content-SHA256"] == receipt["sha256"]
    assert read.headers["Cache-Control"] == "private, no-store"
    for call in rpc.send_command_wait_result.await_args_list:
        assert call.kwargs["live_only"] and call.args[1]["_target_agent_session"] == "test-session"


async def test_permissions_missing_device_and_old_agent_stop_before_rpc(exchange):
    client, url, rpc, report, user = exchange
    user.role = "viewer"
    assert (await client.get(url)).status_code == 403
    user.role = "device_manager"
    unknown = "/api/v1/devices/ff4b4481-c92e-43ca-b6be-20f0a2d89236/files"
    assert (await client.get(unknown)).status_code == 404
    await report(None)
    assert (await client.get(url)).json()["detail"] == "file_exchange_unsupported"
    await report(1, "offline")
    assert (await client.get(url)).json()["detail"] == "file_exchange_offline"
    rpc.send_command_wait_result.assert_not_awaited()


async def test_rejects_oversize_body_invalid_name_and_digest_before_dispatch(exchange):
    client, url, rpc, _, _ = exchange
    too_big = b"x" * (262144 + 1)
    headers = binary_headers(too_big)
    assert (await client.post(f"{url}/big.bin", content=too_big, headers=headers)).status_code == 413

    async def chunks():
        yield too_big[:262144]
        yield too_big[262144:]

    assert (await client.post(f"{url}/big.bin", content=chunks(), headers=headers)).status_code == 413
    assert (await client.get(f"{url}/badname.")).json()["detail"] == "file_invalid_name"
    assert (await client.post(f"{url}/file.bin", content=b"oops", headers=headers)).status_code == 422
    rpc.send_command_wait_result.assert_not_awaited()


async def test_unknown_write_and_read_integrity_failure(exchange):
    client, url, rpc, _, _ = exchange
    headers = binary_headers(b"body")
    rpc.send_command_wait_result.side_effect = [
        {"status": "failed", "error": "private-sentinel"},
        {"status": "completed", "result": {
            "name": "a.txt", "size": 4, "sha256": headers["X-Content-SHA256"], "data": "ZmFpbA==",
        }},
    ]
    written = await client.post(f"{url}/a.txt", headers=headers, content=b"body")
    assert written.status_code == 502 and written.json()["detail"] == "file_exchange_unknown"
    read = await client.get(f"{url}/a.txt")
    assert read.status_code == 502 and read.json()["detail"] == "file_integrity_failed"
