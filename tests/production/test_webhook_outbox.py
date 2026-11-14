"""Runtime-role transaction, restart, deduplication and receiver checks."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select, text, update

from backend.api.ws.android.router import handle_command_result
from backend.core.config import settings
from backend.database.engine import get_db
from backend.database.tenant import bind_tenant_context
from backend.main import app
from backend.models.task import Task, TaskStatus
from backend.models.webhook_delivery import WebhookDelivery
from backend.services import task_service, webhook_outbox
from backend.services import webhook_outbox_worker as worker
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService


@pytest.fixture
def delivery_worker(runtime_db, monkeypatch):
    monkeypatch.setattr(worker, "AsyncSessionLocal", runtime_db.sessions)
    return worker


async def _task(world, destination=None):
    async with world.sessions() as db:
        task = Task(
            org_id=world.org_a.id, device_id=world.dev_a.id, script_id=world.script.id,
            script_version_id=world.version.id, status=TaskStatus.RUNNING,
            input_params={"webhook_url": destination} if destination is not None else {},
        )
        db.add(task)
        await db.commit()
        return task


async def _result(runtime_db, task, *, commit=True, success=True):
    async with runtime_db.sessions() as db:
        await bind_tenant_context(db, str(task.org_id))
        assert await TaskService(db, AsyncMock()).handle_task_result(
            str(task.id), str(task.device_id), {"success": success, "text": "проверка"}, str(task.org_id),
        )
        if commit:
            await db.commit()
        else:
            await db.rollback()


async def _jobs(world, task):
    async with world.sessions() as db:
        return list(await db.scalars(select(WebhookDelivery).where(WebhookDelivery.subject_id == task.id)))


async def _due(world, job):
    async with world.sessions() as db:
        await db.execute(update(WebhookDelivery).where(WebhookDelivery.id == job.id).values(
            next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        ))
        await db.commit()


async def _subscribe(world, url, events=("task.completed",), **fields):
    response = await world.client.post(
        "/api/v1/n8n/webhooks", headers=world.auth(world.users["org_admin"]),
        json={"name": "Audit subscription", "url": url, "events": list(events), **fields},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_atomic_callback_commit_crash_recovery_and_receiver_dedup(runtime_db, delivery_worker):
    world = runtime_db.world
    received = []
    side_effects = set()

    async def receiver(reader, writer):
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            headers = dict(line.decode("ascii").split(": ", 1) for line in head.strip().split(b"\r\n")[1:])
            headers = {key.lower(): value for key, value in headers.items()}
            body = await reader.readexactly(int(headers["content-length"]))
            received.append((headers, body))
            side_effects.add(headers["x-sphere-delivery"])
            writer.write(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(receiver, "127.0.0.1", 0)
    async with server:
        destination = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/resume?token=private"
        task = await _task(world, destination)
        await _result(runtime_db, task, commit=False)
        assert not await _jobs(world, task)
        await _result(runtime_db, task)
        await _result(runtime_db, task)
        job, = await _jobs(world, task)
        assert job.status == "pending" and job.attempts_count == 0 and received == []
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            first, other = await asyncio.gather(
                delivery_worker._claim_job(job.id, job.org_id),
                delivery_worker._claim_job(job.id, job.org_id),
            )
            first, other = (first, other) if first is not None else (other, first)
            assert first is not None and other is None
            first_response = await delivery_worker._send(first, client)
            assert first_response.http_status == 204
            # Receiver accepted, but the worker exits before committing the outcome.
            await _due(world, job)
            second = await delivery_worker._claim_job(job.id, job.org_id)
            assert second is not None and second.token != first.token
            await delivery_worker._complete(first, first_response)
            assert (await _jobs(world, task))[0].status == "sending"
            await delivery_worker._complete(second, await delivery_worker._send(second, client))
    assert len(received) == 2 and side_effects == {str(job.id)}
    assert all("x-sphere-signature" not in headers for headers, _ in received)
    expected = {"event_type": "task.completed", "task_id": str(task.id), "device_id": str(task.device_id),
                "success": True, "result": {"success": True, "text": "проверка"}}
    assert all(json.loads(body) == expected for _, body in received)
    final, = await _jobs(world, task)
    assert final.status == "delivered" and final.attempts_count == 2
    assert final.body is final.signature is final.destination is None and final.body_bytes == 0
    assert [item["status"] for item in final.attempts] == ["unknown", "delivered"]


async def test_subscription_replay_preserves_signed_identity_and_scope(runtime_db, delivery_worker, monkeypatch):
    world = runtime_db.world
    monkeypatch.setattr(settings, "WEBHOOK_SUBSCRIPTIONS_ENABLED", True)
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_ORIGINS", ("https://receiver.example.test",))
    hook = await _subscribe(world, "https://receiver.example.test/sink?private=secret", events=("task.failed",))
    task = await _task(world)
    await _result(runtime_db, task, success=False)
    job, = await _jobs(world, task)
    attempts = []

    async def transport(request):
        attempts.append(request)
        return httpx.Response((429, 403, 204)[len(attempts) - 1], headers={"Retry-After": "900"},
                              content=b"Do not retain this receiver response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport), follow_redirects=False) as client:
        await delivery_worker._process(job.id, job.org_id, client)
        pending, = await _jobs(world, task)
        assert pending.status == "pending" and pending.last_http_status == 429 and pending.last_error == "rate_limited"
        now = datetime.now(timezone.utc)
        assert now + timedelta(seconds=110) < pending.next_attempt_at <= now + timedelta(seconds=120)
        await _due(world, job)
        await delivery_worker._process(job.id, job.org_id, client)
        dead, = await _jobs(world, task)
        assert dead.status == "dead" and dead.attempts_count == 2 and dead.last_http_status == 403

        async def scoped_db():
            async with runtime_db.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = scoped_db
        url = f"/api/v1/n8n/deliveries/{job.id}"
        own = world.auth(world.users["org_admin"])
        foreign = world.auth(world.users["foreign"])
        viewer = world.auth(world.users["viewer"])
        history = await world.client.get("/api/v1/n8n/deliveries", headers=own, params={"status": "dead"})
        assert history.status_code == 200 and history.json()["total"] == 1
        assert history.json()["items"][0]["id"] == str(job.id)
        details = await world.client.get(url, headers=viewer)
        assert details.status_code == 200 and details.json()["can_replay"]
        assert details.headers["Cache-Control"] == "no-store"
        assert all(term not in details.text for term in ("secret", "signature", "destination", "receiver response"))
        assert (await world.client.get(url, headers=foreign)).status_code == 404
        async with world.sessions() as db:
            foreign_user = await db.get(type(world.users["foreign"]), world.users["foreign"].id)
            foreign_user.role = "org_admin"
            await db.commit()
        assert (await world.client.post(url + "/replay", headers=foreign)).status_code == 404
        assert (await world.client.post(url + "/replay", headers=viewer)).status_code == 403
        receipts = await asyncio.gather(*(world.client.post(url + "/replay", headers=own) for _ in range(2)))
        assert sorted(response.status_code for response in receipts) == [200, 409]
        replay = next(response.json() for response in receipts if response.status_code == 200)
        assert replay["id"] == str(job.id) and replay["replay_count"] == 1 and replay["status"] == "pending"
        await delivery_worker._process(job.id, job.org_id, client)
        assert (await world.client.post(url + "/replay", headers=own)).status_code == 409

    assert len(attempts) == 3
    first = attempts[0]
    assert all(request.content == first.content and request.headers == first.headers for request in attempts)
    envelope = json.loads(first.content)
    assert envelope["event"] == "task.failed"
    assert envelope["delivery_id"] == first.headers["X-Sphere-Delivery"] == str(job.id)
    key = hashlib.sha256(hook["secret"].encode()).hexdigest()
    assert first.headers["X-Sphere-Signature"] == "sha256=" + hmac.new(
        key.encode(), first.content, hashlib.sha256,
    ).hexdigest()


@pytest.mark.parametrize("changed", ["paused", "deleted", "allowlist"])
async def test_pending_subscription_uses_current_policy(runtime_db, delivery_worker, monkeypatch, changed):
    world = runtime_db.world
    monkeypatch.setattr(settings, "WEBHOOK_SUBSCRIPTIONS_ENABLED", True)
    monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_ORIGINS", ("https://receiver.example.test",))
    hook = await _subscribe(world, "https://receiver.example.test/sink")
    task = await _task(world)
    await _result(runtime_db, task)
    job, = await _jobs(world, task)
    own = world.auth(world.users["org_admin"])
    url = f"/api/v1/n8n/webhooks/{hook['id']}"
    if changed == "paused":
        assert (await world.client.patch(url, headers=own, json={"is_active": False})).status_code == 200
    elif changed == "deleted":
        assert (await world.client.delete(url, headers=own)).status_code == 204
    else:
        monkeypatch.setattr(settings, "WEBHOOK_ALLOWED_ORIGINS", ())
    assert await delivery_worker._claim_job(job.id, job.org_id) is None
    failed, = await _jobs(world, task)
    assert failed.status == "dead" and failed.attempts_count == 0
    assert failed.last_error == ("receiver_not_allowed" if changed == "allowlist" else "subscription_disabled")
    assert (await world.client.post(f"/api/v1/n8n/deliveries/{job.id}/replay", headers=own)).status_code == 409


async def test_delivery_storage_and_pending_capacity_preserve_result(runtime_db, monkeypatch):
    world = runtime_db.world
    monkeypatch.setattr(webhook_outbox, "MAX_PENDING", 1)
    monkeypatch.setattr(webhook_outbox, "MAX_TENANT_BODY_BYTES", 500)
    monkeypatch.setattr(webhook_outbox, "MAX_HISTORY", 3)
    jobs = []
    for _ in range(4):
        task = await _task(world, "https://receiver.example.test/sink")
        await _result(runtime_db, task)
        job, = await _jobs(world, task)
        jobs.append(job)
    assert [job.last_error for job in jobs] == [
        None, "delivery_capacity_reached", "delivery_storage_capacity", "delivery_storage_capacity",
    ]
    async with world.sessions() as db:
        assert await db.get(WebhookDelivery, jobs[1].id) is None
        assert (await db.get(Task, task.id)).status == TaskStatus.COMPLETED


async def test_worker_discovery_requires_explicit_grant_and_prunes_only_expired(runtime_db, delivery_worker):
    world = runtime_db.world
    task = await _task(world, "https://receiver.example.test/sink")
    await _result(runtime_db, task)
    job, = await _jobs(world, task)
    from sqlalchemy.exc import DBAPIError

    with pytest.raises(DBAPIError):
        await delivery_worker._discover(False)
    async with world.engine.begin() as db:
        await db.execute(text(f'GRANT USAGE ON SCHEMA sphere_auth TO "{runtime_db.role}"'))
        await db.execute(text(f'GRANT EXECUTE ON FUNCTION sphere_auth.webhook_work(boolean) TO "{runtime_db.role}"'))
    try:
        assert (job.id, job.org_id) in await delivery_worker._discover(False)
        await delivery_worker._prune(job.id, job.org_id)
        assert len(await _jobs(world, task)) == 1
        async with world.sessions() as db:
            await db.execute(update(WebhookDelivery).where(WebhookDelivery.id == job.id).values(
                status="dead", updated_at=datetime.now(timezone.utc) - timedelta(days=31),
            ))
            await db.commit()
        assert (job.id, job.org_id) in await delivery_worker._discover(True)
        await delivery_worker._prune(job.id, job.org_id)
        assert not await _jobs(world, task)
    finally:
        async with world.engine.begin() as db:
            await db.execute(text(f'REVOKE EXECUTE ON FUNCTION sphere_auth.webhook_work(boolean) FROM "{runtime_db.role}"'))


async def test_websocket_only_acks_and_releases_after_durable_outbox_commit(runtime_db, monkeypatch):
    world = runtime_db.world
    task = await _task(world, "https://receiver.example.test/sink")
    real_enqueue = task_service.enqueue_task_webhooks
    monkeypatch.setattr("backend.database.engine.AsyncSessionLocal", runtime_db.sessions)
    queue = AsyncMock()
    monkeypatch.setattr(TaskQueue, "mark_completed", queue)
    manager = AsyncMock()
    message = {"command_id": str(task.id), "status": "completed", "result": {"value": "last"}}

    async def fail_enqueue(*args, **kwargs):
        await real_enqueue(*args, **kwargs)
        raise RuntimeError("forced transaction rollback")

    monkeypatch.setattr(task_service, "enqueue_task_webhooks", fail_enqueue)
    await handle_command_result(str(task.device_id), str(task.org_id), message, manager)
    queue.assert_not_awaited()
    manager.send_to_device.assert_not_awaited()
    assert not await _jobs(world, task)
    async with world.sessions() as db:
        assert (await db.get(Task, task.id)).status == TaskStatus.RUNNING

    async def check_queue_release(*args):
        job, = await _jobs(world, task)
        assert job.status == "pending"

    queue.side_effect = check_queue_release
    monkeypatch.setattr(task_service, "enqueue_task_webhooks", real_enqueue)
    await handle_command_result(str(task.device_id), str(task.org_id), message, manager)
    queue.assert_awaited_once_with(str(task.id), str(task.device_id))
    manager.send_to_device.assert_awaited_once_with(
        str(task.device_id), {"type": "result_ack", "command_id": str(task.id)},
    )
