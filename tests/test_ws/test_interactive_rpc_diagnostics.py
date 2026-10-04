"""Actual publisher wait loop: safe progress/timeout evidence, no command replay."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from backend.websocket.pubsub_router import PubSubPublisher, PubSubRouter


class Replies:
    def __init__(self, replies=(), *, stall=False, subscribe_stall=False):
        self.replies = replies
        self.stall = stall
        self.subscribe_stall = subscribe_stall
        self.subscribe = AsyncMock()
        self.aclose = AsyncMock()
        self.listen_count = 0

    async def listen(self):
        self.listen_count += 1
        if self.listen_count == 1:
            if self.subscribe_stall:
                await asyncio.Event().wait()
            yield {"type": "subscribe"}
            return
        for reply in self.replies:
            yield {"type": "message", "data": json.dumps(reply)}
        if self.stall:
            await asyncio.Event().wait()


def fixture(replies):
    redis = MagicMock()
    redis.pubsub.return_value = replies
    redis.publish = AsyncMock(return_value=1)
    command = {"command_id": "interactive_" + str(uuid.uuid4()), "type": "SHELL", "payload": {"cmd": "private-secret-token"}}
    return PubSubPublisher(redis), redis, command


async def test_records_progress_and_terminal_without_private_command_or_result():
    replies = Replies([{"status": "received"}, {"status": "running"}, {"status": "completed", "result": {"output": "private-screen-pixels"}}])
    publisher, redis, command = fixture(replies)
    with patch("backend.websocket.pubsub_router.logger") as logger:
        result = await publisher.send_command_wait_result(str(uuid.uuid4()), command, live_only=True)
    assert result["status"] == "completed"
    event, = logger.info.call_args.args
    fields = logger.info.call_args.kwargs
    assert event == "interactive_rpc.finished"
    assert fields["outcome"] == "completed" and fields["published"] and fields["wait_phase"] == "await_result"
    assert fields["progress_count"] == 2 and fields["last_progress"] == "running" and fields["first_progress_ms"] >= 0
    assert "private" not in repr(fields) and "payload" not in fields and "result" not in fields
    redis.publish.assert_awaited_once()
    replies.aclose.assert_awaited_once()


@pytest.mark.parametrize("stage", ["subscribe", "await_result"])
async def test_timeout_identifies_missing_subscribe_or_terminal_receipt(stage):
    replies = Replies([{"status": "received"}], stall=True, subscribe_stall=stage == "subscribe")
    publisher, redis, command = fixture(replies)
    with patch("backend.websocket.pubsub_router.logger") as logger, pytest.raises(HTTPException) as error:
        await publisher.send_command_wait_result(str(uuid.uuid4()), command, timeout=0.01, live_only=True)
    assert error.value.status_code == 504
    fields = logger.info.call_args.kwargs
    assert fields["outcome"] == "timeout" and fields["wait_phase"] == stage
    assert fields["published"] == (stage == "await_result")
    assert fields["progress_count"] == (1 if stage == "await_result" else 0)
    assert redis.publish.await_count == (1 if stage == "await_result" else 0)
    replies.aclose.assert_awaited_once()


@pytest.mark.parametrize("outcome", ["completed", "unavailable", "timeout"])
async def test_failed_subscription_cleanup_preserves_original_response(outcome):
    replies = Replies([{"status": "completed"}] if outcome == "completed" else [], stall=outcome == "timeout")
    replies.aclose.side_effect = RuntimeError("private close failure")
    publisher, redis, command = fixture(replies)
    if outcome == "unavailable":
        redis.publish.return_value = 0
    with patch("backend.websocket.pubsub_router.logger") as logger:
        if outcome == "completed":
            result = await publisher.send_command_wait_result(str(uuid.uuid4()), command, timeout=0.01, live_only=True)
            assert result["status"] == "completed"
        else:
            with pytest.raises(HTTPException) as error:
                await publisher.send_command_wait_result(str(uuid.uuid4()), command, timeout=0.01, live_only=True)
            assert error.value.status_code == (503 if outcome == "unavailable" else 504)
    fields = logger.info.call_args.kwargs
    assert fields["outcome"] == outcome and fields["subscription_cleanup"] == "unconfirmed"
    assert "private" not in repr(fields)


async def test_accept_progress_does_not_wait_for_terminal_or_add_replay():
    publisher, redis, command = fixture(Replies([{"status": "received"}], stall=True))
    with patch("backend.websocket.pubsub_router.logger") as logger:
        result = await publisher.send_command_wait_result(str(uuid.uuid4()), command, accept_progress=True, live_only=True)
    assert result["status"] == "received" and logger.info.call_args.kwargs["outcome"] == "received"
    redis.publish.assert_awaited_once()


async def test_arbitrary_command_ids_do_not_enter_diagnostic_log():
    publisher, _, command = fixture(Replies([{"status": "completed"}]))
    command["command_id"] = "private-user-command-identifier"
    with patch("backend.websocket.pubsub_router.logger") as logger:
        await publisher.send_command_wait_result("legacy-device", command)
    logger.info.assert_not_called()


async def test_cancelled_wait_preserves_cancellation_and_closes_subscription():
    replies = Replies(stall=True)
    publisher, redis, command = fixture(replies)
    with patch("backend.websocket.pubsub_router.logger") as logger:
        task = asyncio.create_task(publisher.send_command_wait_result(str(uuid.uuid4()), command, live_only=True))
        for _ in range(20):
            if replies.listen_count == 2:
                break
            await asyncio.sleep(0)
        assert replies.listen_count == 2
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert logger.info.call_args.kwargs["outcome"] == "cancelled"
    redis.publish.assert_awaited_once()
    replies.aclose.assert_awaited_once()


@pytest.mark.parametrize("delivered", [True, False])
async def test_worker_forward_receipt_is_distinct_from_redis_publication_and_android_result(delivered):
    manager = MagicMock()
    manager.send_to_device = AsyncMock(return_value=delivered)
    router = PubSubRouter(MagicMock(), manager)
    command_id = "interactive_" + str(uuid.uuid4())
    command = {"command_id": command_id, "type": "SHELL", "payload": {"cmd": "private-root-command"}}
    with patch("backend.websocket.pubsub_router.logger") as logger:
        await router._route_message("sphere:agent:cmd:device", json.dumps(command))
    assert logger.info.call_args.args == ("interactive_rpc.forwarded",)
    fields = logger.info.call_args.kwargs
    assert fields["command_id"] == command_id and fields["socket_send_completed"] == delivered
    assert fields["elapsed_ms"] >= 0 and "private" not in repr(fields)
    manager.send_to_device.assert_awaited_once_with("device", command)
