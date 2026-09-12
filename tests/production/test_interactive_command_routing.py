"""Interactive HTTP requests must reach a WS owned by another worker via real Redis."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.websocket.connection_manager import ConnectionManager
from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter


@pytest.mark.parametrize("endpoint,body,command_type,expected", [
    ("shell", {"command": "echo isolated"}, "SHELL", {"output": "isolated\n"}),
    ("logcat", {"lines": 10, "mode": "sphere"}, "UPLOAD_LOGCAT", {"logcat": "isolated-log"}),
    ("reboot", None, "REBOOT", None),
])
async def test_interactive_request_reaches_another_worker_and_keeps_immediate_result(
    world, endpoint, body, command_type, expected,
):
    api_manager = ConnectionManager()  # The HTTP worker owns no socket.
    owner_manager = ConnectionManager()
    delivered = []
    device_id = str(world.dev_a.id)

    async def reply(command):
        delivered.append(command)
        # Return while delivery is still in progress: subscribing afterwards loses it.
        await world.redis.publish(f"sphere:agent:result:{device_id}:{command['command_id']}",
            json.dumps({"status": "completed", "result": {"output": "isolated\n", "logcat": "isolated-log"}}))

    await owner_manager.connect(AsyncMock(send_json=reply), device_id, "android", str(world.org_a.id))
    router = PubSubRouter(world.redis, owner_manager)
    publisher = PubSubPublisher(world.redis)
    await router.start()
    await router.subscribe_device(device_id, str(world.org_a.id))
    try:
        with patch("backend.websocket.connection_manager.get_connection_manager", return_value=api_manager), \
             patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
            response = await asyncio.wait_for(world.client.post(f"/api/v1/devices/{device_id}/{endpoint}",
                headers=world.auth(world.users['org_admin']), json=body), 10)
        assert response.status_code == 200, response.text
        assert len(delivered) == 1 and delivered[0]["type"] == command_type
        if expected is None:
            assert response.json() == {"status": "reboot_initiated", "device_id": device_id}
        else:
            assert response.json() == expected
    finally:
        await router.stop()


@pytest.mark.parametrize("endpoint,body", [
    ("shell", {"command": "echo isolated"}), ("logcat", {"lines": 10}), ("reboot", None),
])
async def test_offline_interactive_command_is_rejected_without_deferred_execution(world, endpoint, body):
    publisher = PubSubPublisher(world.redis)
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher), \
         patch.object(publisher, "_send_command_inner", AsyncMock()) as queued:
        response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/{endpoint}",
            headers=world.auth(world.users['org_admin']), json=body)
    assert response.status_code == 503
    queued.assert_not_awaited()


@pytest.mark.parametrize("endpoint,body", [
    ("shell", {"command": "echo isolated"}), ("logcat", {"lines": 10}), ("reboot", None),
])
async def test_foreign_device_is_denied_before_any_command_publication(world, endpoint, body):
    publisher = AsyncMock()
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.post(f"/api/v1/devices/{world.dev_b.id}/{endpoint}",
            headers=world.auth(world.users['org_admin']), json=body)
    assert response.status_code == 404
    publisher.send_command_wait_result.assert_not_awaited()


async def test_reboot_timeout_reports_unknown_outcome_instead_of_success(world):
    publisher = AsyncMock()
    publisher.send_command_wait_result.side_effect = HTTPException(504, "isolated timeout")
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/reboot",
            headers=world.auth(world.users['org_admin']))
    assert response.status_code == 504
    assert "unknown" in response.json()["detail"]


async def test_reboot_can_return_on_received_ack_without_waiting_for_disconnected_device(world):
    publisher = PubSubPublisher(world.redis)
    device_id = str(world.dev_a.id)

    async def received(_device, command):
        await world.redis.publish(f"sphere:agent:result:{device_id}:{command['command_id']}",
            json.dumps({"status": "received"}))
        return True

    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher), \
         patch.object(publisher, "send_command_live", side_effect=received):
        response = await asyncio.wait_for(world.client.post(f"/api/v1/devices/{device_id}/reboot",
            headers=world.auth(world.users['org_admin'])), 3)
    assert response.status_code == 200
    assert response.json()["status"] == "reboot_initiated"


async def test_unavailable_redis_transport_does_not_claim_device_offline(world):
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=None):
        response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/shell",
            headers=world.auth(world.users['org_admin']), json={"command": "echo isolated"})
    assert response.status_code == 503
    assert "transport" in response.json()["detail"]
