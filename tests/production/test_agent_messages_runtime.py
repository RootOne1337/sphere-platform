"""Post-auth Android messages must bind each fresh non-owner SQL session."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_agent_tenant_runtime import agent_runtime, websocket  # noqa: F401
from test_device_bootstrap_runtime import issue_device, wait_for_two_runtime_locks

from backend.core.audit_identity import TASK_AGENT_RESULT, TASK_EXECUTION_REQUESTED
from backend.models.audit_log import AuditLog
from backend.models.device_event import DeviceEvent
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.models.webhook_delivery import WebhookDelivery
from backend.services import webhook_outbox_worker


@pytest.fixture
def message_runtime(agent_runtime, monkeypatch):
    r = agent_runtime
    # The router imports the factory both at module level (auth/progress) and
    # inside handlers (receipts/results/events). Both must use the actual role.
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", r.db.sessions)
    monkeypatch.setattr("backend.database.redis_client.redis", r.world.redis)
    r.manager.send_to_device = AsyncMock(return_value=True)
    return r


async def make_task(r, device_id, status=TaskStatus.ASSIGNED, org_id=None):
    w = r.world
    async with w.sessions() as db:
        batch = TaskBatch(org_id=org_id or w.org_a.id, script_id=w.script.id,
                          status=TaskBatchStatus.RUNNING, total=1)
        db.add(batch)
        await db.flush()
        task = Task(org_id=batch.org_id, device_id=device_id, script_id=w.script.id,
                    batch_id=batch.id, status=status)
        db.add(task)
        await db.commit()
    return task


def result_message(task, status, typed=True):
    return {**({"type": "command_result"} if typed else {}),
            "command_id": str(task.id), "status": status,
            "result": {"value": "first", "success": status != "completed"}}


def task_agent_audit(task):
    return select(AuditLog).where(
        AuditLog.resource_id == str(task.id), AuditLog.action == TASK_AGENT_RESULT,
    )


async def assert_unscoped(r):
    async with r.db.sessions() as db:
        assert await db.scalar(text("SELECT current_user")) == r.db.role
        assert await db.scalar(text("SELECT nullif(current_setting('app.current_org_id', true), '')")) is None
        assert await db.scalar(select(func.count()).select_from(Task)) == 0
        assert await db.scalar(select(func.count()).select_from(DeviceEvent)) == 0
        assert await db.scalar(select(func.count()).select_from(WebhookDelivery)) == 0
        assert await db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("status", ["received", "running"])
@pytest.mark.parametrize("typed", [True, False])
async def test_runtime_task_receipt_persists_start(message_runtime, status, typed):
    r = message_runtime
    enrolled = await issue_device(r.world)
    task = await make_task(r, enrolled.device_id)
    message = result_message(task, status, typed)
    for _ in range(2):
        await websocket(enrolled.device_id, enrolled.access_token, [message])
        async with r.world.sessions() as db:
            saved = await db.get(Task, task.id)
            assert saved.status == TaskStatus.RUNNING
            assert saved.started_at is not None
            if _ == 0:
                started_at = saved.started_at
            else:
                assert saved.started_at == started_at
    r.manager.send_to_device.assert_not_awaited()  # terminal receipts only
    await assert_unscoped(r)


@pytest.mark.parametrize("status", ["completed", "failed"])
@pytest.mark.parametrize("redis_outage", [False, True])
async def test_runtime_result_commit_ack_and_reconnect_replay(message_runtime, monkeypatch, status, redis_outage):
    r = message_runtime
    enrolled = await issue_device(r.world)
    task = await make_task(r, enrolled.device_id, TaskStatus.RUNNING)
    confirmed_commits = []

    async def check_commit(device_id, message):
        assert device_id == str(enrolled.device_id)
        assert message == {"type": "result_ack", "command_id": str(task.id)}
        async with r.world.sessions() as db:
            saved = await db.get(Task, task.id)
            assert saved.status == status
            assert saved.finished_at is not None
            assert saved.result == {"value": "first", "success": status == "completed"}
            batch = await db.get(TaskBatch, task.batch_id)
            assert (batch.succeeded, batch.failed) == (int(status == "completed"), int(status == "failed"))
            assert batch.status == status
            assert await db.scalar(select(func.count()).select_from(DeviceEvent).where(DeviceEvent.task_id == task.id)) == 1
            audit, = (await db.scalars(task_agent_audit(task))).all()
            assert audit.org_id == r.world.org_a.id and audit.user_id is None
            assert audit.meta == {
                "status": "success" if status == "completed" else "failure",
                "agent_outcome": status, "device_id": str(enrolled.device_id), "receipt_id": str(task.id),
            }
        # The production handler catches send errors. Keep a success marker so
        # an assertion raised inside this callback cannot be swallowed by it.
        confirmed_commits.append(True)
        return True

    r.manager.send_to_device.side_effect = check_commit
    if redis_outage:
        for method in ("publish", "get", "eval"):
            monkeypatch.setattr(r.world.redis, method, AsyncMock(side_effect=ConnectionError("isolated Redis outage")))
    message = result_message(task, status, typed=False)  # APK CommandAck format
    await websocket(enrolled.device_id, enrolled.access_token, [message])
    # A conflicting replay after reconnect may acknowledge the existing durable
    # result, but must not replace its payload, event or batch accounting.
    replay = result_message(task, "failed" if status == "completed" else "completed")
    await websocket(enrolled.device_id, enrolled.access_token, [replay])
    assert r.manager.send_to_device.await_count == 2
    assert confirmed_commits == [True, True]
    await assert_unscoped(r)


@pytest.mark.parametrize("target", ["own", "same_org_other", "foreign", "terminal"])
async def test_runtime_progress_and_result_ownership(message_runtime, target):
    r = message_runtime
    enrolled = await issue_device(r.world)
    device_id = {"same_org_other": r.world.dev_a2.id, "foreign": r.world.dev_b.id}.get(target, enrolled.device_id)
    task = await make_task(r, device_id,
                          TaskStatus.COMPLETED if target == "terminal" else TaskStatus.ASSIGNED,
                          r.world.org_b.id if target == "foreign" else None)
    progress = {"type": "task_progress", "task_id": str(task.id), "current_node": "step",
                "nodes_done": 1, "total_nodes": 2,
                "org_id": str(r.world.org_b.id), "device_id": str(r.world.dev_b.id)}
    await websocket(enrolled.device_id, enrolled.access_token, [progress])
    cached = await r.world.redis.hgetall(f"task_progress:{task.id}")
    if target == "own":
        assert cached["progress"] == "50"
        assert cached["current_node"] == "step"
        assert await r.world.redis.llen(f"task_progress_log:{task.id}") == 1
        assert 0 < await r.world.redis.ttl(f"task_progress:{task.id}") <= 600
    else:
        assert cached == {}
        assert not await r.world.redis.exists(f"task_progress_log:{task.id}")
    if target in {"same_org_other", "foreign"}:
        await websocket(enrolled.device_id, enrolled.access_token,
                        [result_message(task, "received"), result_message(task, "completed")])
        r.manager.send_to_device.assert_not_awaited()
        async with r.world.sessions() as db:
            assert (await db.get(Task, task.id)).status == TaskStatus.ASSIGNED
            assert (await db.get(TaskBatch, task.batch_id)).succeeded == 0
    if target != "own":
        if target == "terminal":
            await websocket(enrolled.device_id, enrolled.access_token, [result_message(task, "completed")])
            r.manager.send_to_device.assert_awaited_once()  # Existing terminal ACK behavior.
        async with r.world.sessions() as db:
            assert await db.scalar(task_agent_audit(task)) is None
    await assert_unscoped(r)


async def test_runtime_event_uses_authenticated_identity(message_runtime):
    r = message_runtime
    enrolled = await issue_device(r.world)
    await websocket(enrolled.device_id, enrolled.access_token, [{
        "type": "event", "event_type": "device.audit_probe", "severity": "info",
        "message": "isolated event", "data": {"sample": 1},
        "org_id": str(r.world.org_b.id), "device_id": str(r.world.dev_b.id),
    }])
    async with r.world.sessions() as db:
        event = await db.scalar(select(DeviceEvent).where(DeviceEvent.device_id == enrolled.device_id))
        assert event is not None
        assert event.org_id == r.world.org_a.id
        assert event.processed is True and event.data == {"sample": 1}
    await assert_unscoped(r)


async def test_runtime_result_sql_abort_has_no_ack_and_replay_recovers(message_runtime, monkeypatch):
    r = message_runtime
    enrolled = await issue_device(r.world)
    task = await make_task(r, enrolled.device_id, TaskStatus.RUNNING)
    async with r.world.sessions() as db:
        stored = await db.get(Task, task.id)
        stored.input_params = {"webhook_url": "https://callback.example.test/result"}
        await db.commit()
    message = result_message(task, "completed")
    reached_commit = []
    deliveries = []
    monkeypatch.setattr(webhook_outbox_worker, "AsyncSessionLocal", r.db.sessions)

    async def receiver(request):
        async with r.world.sessions() as db:
            deliveries.append((
                request.url.path, (await db.get(Task, task.id)).status, request.headers["X-Sphere-Delivery"],
            ))
        return httpx.Response(204)

    @asynccontextmanager
    async def failing_sessions():
        async with r.db.sessions() as db:
            async def abort_commit():
                await db.flush()
                reached_commit.append(True)
                await db.execute(text("SELECT 1/0"))  # real aborted PostgreSQL transaction
            monkeypatch.setattr(db, "commit", abort_commit)
            yield db

    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", failing_sessions)
    await websocket(enrolled.device_id, enrolled.access_token, [message])
    assert reached_commit == [True]
    r.manager.send_to_device.assert_not_awaited()
    assert deliveries == []
    async with r.world.sessions() as db:
        saved = await db.get(Task, task.id)
        assert saved.status == TaskStatus.RUNNING and saved.result is None
        assert (await db.get(TaskBatch, task.batch_id)).succeeded == 0
        assert await db.scalar(select(func.count()).select_from(DeviceEvent).where(DeviceEvent.task_id == task.id)) == 0
        assert await db.scalar(select(WebhookDelivery.id).where(WebhookDelivery.subject_id == task.id)) is None
        assert await db.scalar(task_agent_audit(task)) is None
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", r.db.sessions)
    await websocket(enrolled.device_id, enrolled.access_token, [message])
    r.manager.send_to_device.assert_awaited_once()
    assert deliveries == []
    async with r.world.sessions() as db:
        delivery, = (await db.scalars(select(WebhookDelivery).where(WebhookDelivery.subject_id == task.id))).all()
        assert delivery.status == "pending" and delivery.attempts_count == 0
    await websocket(enrolled.device_id, enrolled.access_token, [message])
    assert r.manager.send_to_device.await_count == 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as client:
        await webhook_outbox_worker._process(delivery.id, delivery.org_id, client)
        await webhook_outbox_worker._process(delivery.id, delivery.org_id, client)
    assert deliveries == [("/result", TaskStatus.COMPLETED, str(delivery.id))]
    async with r.world.sessions() as db:
        assert (await db.get(Task, task.id)).status == TaskStatus.COMPLETED
        assert (await db.get(TaskBatch, task.batch_id)).succeeded == 1
        saved_delivery, = (await db.scalars(select(WebhookDelivery).where(WebhookDelivery.subject_id == task.id))).all()
        assert saved_delivery.status == "delivered" and saved_delivery.attempts_count == 1
        audit, = (await db.scalars(task_agent_audit(task))).all()
        assert audit.meta["receipt_id"] == str(task.id)
    await assert_unscoped(r)


async def test_runtime_concurrent_result_replay_counts_once(message_runtime, monkeypatch):
    r = message_runtime
    enrolled = await issue_device(r.world)
    task = await make_task(r, enrolled.device_id, TaskStatus.RUNNING)
    message = result_message(task, "completed")
    engine = create_async_engine(r.db.engine.url, pool_size=3, max_overflow=0)
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    calls = []
    try:
        async with r.world.sessions() as blocker:
            await blocker.scalar(select(Task).where(Task.id == task.id).with_for_update())
            calls = [asyncio.create_task(websocket(enrolled.device_id, enrolled.access_token, [message])) for _ in range(2)]
            await wait_for_two_runtime_locks(r.db)
            await blocker.commit()
        await asyncio.gather(*calls)
        assert r.manager.send_to_device.await_count == 2
        async with r.world.sessions() as db:
            assert (await db.get(Task, task.id)).status == TaskStatus.COMPLETED
            assert (await db.get(TaskBatch, task.batch_id)).succeeded == 1
            assert await db.scalar(select(func.count()).select_from(DeviceEvent).where(DeviceEvent.task_id == task.id)) == 1
            assert len((await db.scalars(task_agent_audit(task))).all()) == 1
    finally:
        for call in calls:
            if not call.done():
                call.cancel()
        await asyncio.gather(*calls, return_exceptions=True)
        await engine.dispose()
    await assert_unscoped(r)



@pytest.mark.parametrize(("path", "action"), [("", "post.tasks"), ("/rerun", "post.tasks.rerun")])
async def test_runtime_audit_correlates_operator_request_and_authenticated_agent_receipt(message_runtime, monkeypatch, path, action):
    from backend.main import app

    r = message_runtime
    enrolled = await issue_device(r.world)
    request_id = "audit-correlate-agent-result"
    if path:
        original = await make_task(r, enrolled.device_id, TaskStatus.COMPLETED)
        async with r.world.sessions() as db:
            source = await db.get(Task, original.id)
            source.script_version_id = r.world.script.current_version_id
            await db.commit()
        url = f"/api/v1/tasks/{original.id}/rerun"
        payload = None
    else:
        url = "/api/v1/tasks"
        payload = {"script_id": str(r.world.script.id), "device_id": str(enrolled.device_id)}
    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", r.db.sessions)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://audit.local") as client:
        headers = {**r.world.auth(r.world.users["org_admin"]), "X-Request-ID": request_id}
        response = await client.post(url, json=payload, headers=headers)
        assert response.status_code == 201, response.text
        assert response.headers["X-Request-ID"] == request_id
        created = response.json()
        async with r.world.sessions() as db:
            queued = await db.scalar(select(Task).where(Task.id == uuid.UUID(created["id"])))
            assert queued.status == TaskStatus.QUEUED
        message = {
            "command_id": created["id"], "status": "completed", "type": "command_result",
            "device_id": str(r.world.dev_b.id), "org_id": str(r.world.org_b.id),
            "result": {"device_id": str(r.world.dev_b.id), "auth_token": "private-agent-output"},
        }
        await websocket(enrolled.device_id, enrolled.access_token, [message])
        r.manager.send_to_device.assert_not_awaited()
        async with r.world.sessions() as db:
            task = await db.get(Task, queued.id)
            assert task.status == TaskStatus.QUEUED
            assert await db.scalar(task_agent_audit(task)) is None
            task.status = TaskStatus.ASSIGNED
            await db.commit()
        await websocket(enrolled.device_id, enrolled.access_token, [message, message])
        assert r.manager.send_to_device.await_count == 2

        audit = await client.get("/api/v1/audit/logs", params={"q": f"request:{request_id}"}, headers=headers)
        assert audit.status_code == 200, audit.text
        records = {item["action"]: item for item in audit.json()["items"]}
        assert len(audit.json()["items"]) == len(records) == 3
        assert set(records) == {TASK_AGENT_RESULT, TASK_EXECUTION_REQUESTED, action}
        admission, result, http = records[TASK_EXECUTION_REQUESTED], records[TASK_AGENT_RESULT], records[action]
        assert admission["resource_id"] == result["resource_id"] == created["id"]
        assert admission["user_id"] == http["user_id"] == str(r.world.users["org_admin"].id)
        assert result["user_id"] is None
        assert result["meta"] == {
            "status": "success", "request_id": request_id, "agent_outcome": "completed",
            "receipt_id": created["id"], "device_id": str(enrolled.device_id),
            "requested_by": admission["user_id"],
        }
        assert http["meta"]["http_status"] == 201
        assert result["old_value"] is result["new_value"] is None
        assert "private-agent-output" not in audit.text


@pytest.mark.parametrize(("result", "error", "outcome", "task_status"), [
    ({"cancelled": True}, "private-stop-detail", "cancelled", TaskStatus.CANCELLED),
    ({}, "execution_outcome_unknown_after_restart", "unknown", TaskStatus.FAILED),
])
async def test_runtime_agent_receipt_classifies_cancelled_and_unknown_without_payload(
    message_runtime, result, error, outcome, task_status,
):
    r = message_runtime
    enrolled = await issue_device(r.world)
    task = await make_task(r, enrolled.device_id, TaskStatus.RUNNING)
    await websocket(enrolled.device_id, enrolled.access_token, [
        {"type": "command_result", "command_id": str(task.id), "status": "failed",
         "error": error, "result": result},
    ])
    r.manager.send_to_device.assert_awaited_once()
    async with r.world.sessions() as db:
        saved = await db.get(Task, task.id)
        assert saved.status == task_status and saved.result["error"] == error
        receipt, = (await db.scalars(task_agent_audit(task))).all()
        assert receipt.meta == {
            "status": "warning" if outcome == "cancelled" else "unknown",
            "agent_outcome": outcome, "device_id": str(enrolled.device_id), "receipt_id": str(task.id),
        }
    await assert_unscoped(r)
