"""Link the real PC dispatcher to the backend's Redis command-result channel."""

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from agent.dispatcher import CommandDispatcher
from test_pc_tenant_runtime import pc_runtime, router  # noqa: F401


async def subscribe(r, command_id):
    sub = r.world.redis.pubsub()
    await sub.subscribe(f"sphere:agent:result:{r.own.id}:{command_id}")
    receipt = await sub.get_message(timeout=1)
    assert receipt and receipt["type"] == "subscribe"
    return sub


async def deliver(r, message):
    async with r.db.sessions() as db:
        await router.handle_agent_message(str(r.own.id), str(r.own.org_id), message, r.manager, db)


@pytest.mark.parametrize("failure", [False, True])
async def test_pc_dispatch_result_reaches_waiting_server_channel(pc_runtime, failure):
    r = pc_runtime
    command_id = str(uuid.uuid4())
    ldplayer = AsyncMock()
    ldplayer.quit.side_effect = RuntimeError("isolated command failure")
    dispatcher = CommandDispatcher(ldplayer, AsyncMock())
    sent = []

    class Transport:
        async def send(self, message):
            sent.append(message)
            await deliver(r, message)
    dispatcher.ws_client = Transport()
    sub = await subscribe(r, command_id)
    try:
        await dispatcher.dispatch({"type": "ld_quit" if failure else "ping",
                                   "command_id": command_id, "payload": {"index": 0}})
        received = await sub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        assert received is not None, "The PC executed/rejected the command but the backend discarded its result"
        result = json.loads(received["data"])
        assert result == sent[0]
        assert result["type"] == "command_result"
        assert result["command_id"] == command_id
        assert result["status"] == ("failed" if failure else "completed")
        if failure:
            assert result["error"] == "isolated command failure"
        else:
            assert result["result"] == {"pong": True}
    finally:
        await sub.aclose()


@pytest.mark.parametrize("status", ["completed", "failed"])
async def test_server_accepts_legacy_pc_terminal_reply(pc_runtime, status):
    r = pc_runtime
    command_id = str(uuid.uuid4())
    message = {"command_id": command_id, "status": status, "result": {"legacy": True}}
    sub = await subscribe(r, command_id)
    try:
        await deliver(r, message)
        received = await sub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        assert received is not None
        assert json.loads(received["data"]) == message
    finally:
        await sub.aclose()


async def test_server_preserves_typed_pc_reply(pc_runtime):
    r = pc_runtime
    command_id = str(uuid.uuid4())
    message = {"type": "command_result", "command_id": command_id, "status": "completed"}
    sub = await subscribe(r, command_id)
    try:
        await deliver(r, message)
        received = await sub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        assert received is not None and json.loads(received["data"]) == message
    finally:
        await sub.aclose()


@pytest.mark.parametrize("status", ["received", "running", "unknown", None])
async def test_untyped_nonterminal_message_is_not_a_pc_result(pc_runtime, status):
    r = pc_runtime
    command_id = str(uuid.uuid4())
    sub = await subscribe(r, command_id)
    try:
        await deliver(r, {"command_id": command_id, "status": status})
        assert await sub.get_message(ignore_subscribe_messages=True, timeout=0.1) is None
    finally:
        await sub.aclose()


async def test_telemetry_with_result_fields_is_not_reclassified(pc_runtime):
    r = pc_runtime
    command_id = str(uuid.uuid4())
    sub = await subscribe(r, command_id)
    try:
        await deliver(r, {"type": "workstation_telemetry", "command_id": command_id,
                          "status": "completed", "payload": {"sample": 1}})
        assert await sub.get_message(ignore_subscribe_messages=True, timeout=0.1) is None
    finally:
        await sub.aclose()
