"""Runtime invariants on disposable PostgreSQL and Redis (opt-in)."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


async def test_command_wait_has_real_deadline(world):
    from backend.websocket.pubsub_router import PubSubPublisher

    publisher = PubSubPublisher(world.redis)
    with patch.object(publisher, "_send_command_inner", AsyncMock(return_value=(True, False))):
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(
                publisher.send_command_wait_result(str(uuid.uuid4()), {}, timeout=0.03), timeout=0.5
            )
        assert error.value.status_code == 504


async def test_intermediate_ack_does_not_finish_command_wait(world):
    from backend.websocket.pubsub_router import PubSubPublisher

    publisher = PubSubPublisher(world.redis)
    device_id = str(uuid.uuid4())

    async def reply(_device, command):
        channel = f"sphere:agent:result:{device_id}:{command['command_id']}"
        await world.redis.publish(channel, json.dumps({"status": "received"}))
        await world.redis.publish(channel, json.dumps({"status": "running"}))
        await world.redis.publish(channel, json.dumps({"status": "completed", "result": {"ok": True}}))
        return True, False

    with patch.object(publisher, "_send_command_inner", side_effect=reply):
        result = await publisher.send_command_wait_result(device_id, {}, timeout=0.5)
    assert result == {"status": "completed", "result": {"ok": True}}


async def test_deadline_also_bounds_command_delivery(world):
    from backend.websocket.pubsub_router import PubSubPublisher

    publisher = PubSubPublisher(world.redis)

    async def stalled_delivery(*_args):
        await asyncio.sleep(10)

    with patch.object(publisher, "_send_command_inner", side_effect=stalled_delivery):
        with pytest.raises(HTTPException) as error:
            await asyncio.wait_for(publisher.send_command_wait_result(str(uuid.uuid4()), {}, timeout=0.03), 0.5)
        assert error.value.status_code == 504
