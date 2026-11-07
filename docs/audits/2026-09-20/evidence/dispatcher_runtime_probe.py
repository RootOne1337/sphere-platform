"""Disposable SQL plus a transport double; never contact an Android device."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.database.tenant import bind_tenant_context
from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


async def test_runtime_dispatcher_reads_queue_without_http_tenant_context(runtime_db):
    r = runtime_db
    async with r.world.sessions() as db:
        task = Task(org_id=r.world.org_a.id, device_id=r.world.dev_a.id,
            script_id=r.world.script.id, script_version_id=r.world.version.id,
            status=TaskStatus.QUEUED)
        db.add(task)
        await db.commit()
    cache, publisher = AsyncMock(), AsyncMock()
    cache.bulk_get_status.return_value = {str(r.world.dev_a.id): SimpleNamespace(status="online")}
    publisher.send_command_live.return_value = True
    async with r.sessions() as db:
        await TaskService(db, AsyncMock(), status_cache=cache, publisher=publisher).dispatch_pending_tasks()
    async with r.world.sessions() as db:
        unscoped_status = (await db.get(Task, task.id)).status
    assert publisher.send_command_live.await_count == 0
    async with r.sessions() as db:
        await bind_tenant_context(db, str(r.world.org_a.id))
        await TaskService(db, AsyncMock(), status_cache=cache, publisher=publisher).dispatch_pending_tasks()
    async with r.world.sessions() as db:
        scoped_status = (await db.get(Task, task.id)).status
    assert scoped_status == TaskStatus.ASSIGNED and publisher.send_command_live.await_count == 1
    assert unscoped_status == TaskStatus.ASSIGNED, "Unscoped startup leaves queued task invisible; binding same role permits assignment"
