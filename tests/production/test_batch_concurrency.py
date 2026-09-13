"""Concurrent results and watchdog ticks must not lose batch completion counts."""

import asyncio
from datetime import datetime, timezone

import pytest

from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.services.task_service import TaskService
from backend.tasks.task_heartbeat_watchdog import _aggregate_batches


@pytest.mark.parametrize("other_writer", ["success", "failure", "watchdog"])
async def test_batch_accounting_serializes_independent_terminal_results(world, other_writer):
    w = world
    async with w.sessions() as db:
        batch = TaskBatch(org_id=w.org_a.id, script_id=w.script.id, total=2)
        db.add(batch)
        await db.flush()
        tasks = [Task(org_id=w.org_a.id, device_id=device.id, script_id=w.script.id,
            status=TaskStatus.RUNNING, batch_id=batch.id) for device in [w.dev_a, w.dev_a2]]
        db.add_all(tasks)
        await db.commit()

    async with w.sessions() as first, w.sessions() as second:
        # A long-lived worker can have an old identity-map value before acquiring
        # the row lock. The locked read must refresh that object as well.
        stale_batch = await second.get(TaskBatch, batch.id)
        await TaskService(first).handle_task_result(str(tasks[0].id), str(w.dev_a.id), {"success": True})

        async def finish_other():
            if other_writer == "watchdog":
                timed = await second.get(Task, tasks[1].id)
                timed.status = TaskStatus.TIMEOUT
                await _aggregate_batches(second, [timed], datetime.now(timezone.utc), TaskBatch, TaskBatchStatus)
            else:
                await TaskService(second).handle_task_result(
                    str(tasks[1].id), str(w.dev_a2.id), {"success": other_writer == "success"},
                )
            await second.commit()

        pending = asyncio.create_task(finish_other())
        try:
            await asyncio.wait({pending}, timeout=0.15)
            await first.commit()
            await asyncio.wait_for(pending, 3)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await second.refresh(stale_batch)
        assert stale_batch.succeeded == (2 if other_writer == "success" else 1)
        assert stale_batch.failed == (0 if other_writer == "success" else 1)
        assert stale_batch.status == (
            TaskBatchStatus.COMPLETED if other_writer == "success" else TaskBatchStatus.PARTIAL
        )
