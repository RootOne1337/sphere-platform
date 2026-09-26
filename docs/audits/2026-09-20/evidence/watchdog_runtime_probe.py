"""Diagnostic baseline outside passing CI: watchdog RLS visibility, no APK I/O."""

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from backend.database.tenant import bind_tenant_context
from backend.models.task import Task, TaskStatus
from backend.tasks import task_heartbeat_watchdog as watchdog


async def test_runtime_watchdog_can_find_undelivered_expired_task(runtime_db, monkeypatch):
    r = runtime_db
    async with r.world.sessions() as db:
        task = Task(org_id=r.world.org_a.id, device_id=r.world.dev_a.id,
                    script_id=r.world.script.id, script_version_id=r.world.version.id,
                    status=TaskStatus.QUEUED, created_at=datetime.now(timezone.utc)-timedelta(hours=2))
        db.add(task)
        await db.commit()
    monkeypatch.setattr(watchdog, "AsyncSessionLocal", r.sessions)
    monkeypatch.setattr("backend.database.redis_client.redis_binary", None)
    monkeypatch.setattr(watchdog, "_QUEUED_STALE_MINUTES", 60)
    await watchdog._expire_stale_tasks()
    async with r.world.sessions() as db:
        unscoped = (await db.get(Task, task.id)).status

    @asynccontextmanager
    async def bound_sessions():
        async with r.sessions() as db:
            await bind_tenant_context(db, str(r.world.org_a.id))
            yield db

    monkeypatch.setattr(watchdog, "AsyncSessionLocal", bound_sessions)
    await watchdog._expire_stale_tasks()
    async with r.world.sessions() as db:
        bound = (await db.get(Task, task.id)).status
    print(json.dumps({"watchdog_probe": {"unscoped_status": unscoped, "bound_status": bound}}))
    assert bound == TaskStatus.TIMEOUT
    assert unscoped == TaskStatus.TIMEOUT, "Startup watchdog cannot discover expired queued task under RLS"
