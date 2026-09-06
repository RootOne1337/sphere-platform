"""Cancel/stop must serialize with terminal results and refresh ORM snapshots."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


async def seed_task(world, status):
    async with world.sessions() as db:
        task = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                    script_id=world.script.id, script_version_id=world.version.id, status=status)
        db.add(task)
        await db.commit()
    return task


@pytest.mark.parametrize("method,initial", [
    ("cancel_task", TaskStatus.ASSIGNED), ("force_stop_task", TaskStatus.RUNNING),
])
@pytest.mark.parametrize("terminal", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT])
async def test_stale_cancellation_cannot_overwrite_a_terminal_result(world, method, initial, terminal):
    task = await seed_task(world, initial)
    queue, publisher = AsyncMock(), AsyncMock()
    async with world.sessions() as cancellation:
        cached = await cancellation.get(Task, task.id)
        async with world.sessions() as completion:
            latest = await completion.get(Task, task.id)
            latest.status = terminal
            latest.finished_at = datetime.now(timezone.utc)
            latest.result = {"audit": "committed-terminal-result"}
            await completion.commit()
        assert cached.status == initial  # Reproduce the real identity-map snapshot.
        service = TaskService(cancellation, queue, publisher=publisher)
        try:
            await getattr(service, method)(task.id, world.org_a.id)
            await cancellation.commit()
            outcome = 200
        except HTTPException as exc:
            await cancellation.rollback()
            outcome = exc.status_code
    async with world.sessions() as verify:
        stored = await verify.get(Task, task.id)
        assert stored.status == terminal, "Cancellation overwrote a newer committed terminal state"
        assert stored.result == {"audit": "committed-terminal-result"}
    assert outcome == 409
    queue.cancel_task.assert_not_awaited()
    queue.mark_completed.assert_not_awaited()
    publisher.send_command_live.assert_not_awaited()


@pytest.mark.parametrize("method,initial", [
    ("cancel_task", TaskStatus.ASSIGNED), ("force_stop_task", TaskStatus.RUNNING),
])
async def test_cancellation_waits_for_the_result_owner_before_external_effects(world, method, initial):
    task = await seed_task(world, initial)
    queue, publisher = AsyncMock(), AsyncMock()
    async with world.sessions() as cancellation, world.sessions() as completion:
        cached = await cancellation.get(Task, task.id)
        latest = await completion.scalar(select(Task).where(Task.id == task.id).with_for_update())
        latest.status = TaskStatus.COMPLETED
        await completion.flush()  # Row remains locked with an uncommitted terminal result.

        async def request():
            try:
                await getattr(TaskService(cancellation, queue, publisher=publisher), method)(task.id, world.org_a.id)
                await cancellation.commit()
                return 200
            except HTTPException as exc:
                await cancellation.rollback()
                return exc.status_code

        pending = asyncio.create_task(request())
        try:
            await asyncio.wait({pending}, timeout=0.15)
            effects_before_commit = queue.cancel_task.await_count + queue.mark_completed.await_count + publisher.send_command_live.await_count
            await completion.commit()
            assert await asyncio.wait_for(pending, 3) == 409
            assert effects_before_commit == 0
            assert (await cancellation.get(Task, task.id)).status == TaskStatus.COMPLETED
            assert cached.id == task.id  # Keep the original identity-map object alive.
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.parametrize("method", ["cancel_task", "force_stop_task"])
async def test_locked_cancellation_preserves_the_tenant_boundary(world, method):
    task = await seed_task(world, TaskStatus.QUEUED)
    queue, publisher = AsyncMock(), AsyncMock()
    async with world.sessions() as db:
        with pytest.raises(HTTPException) as caught:
            await getattr(TaskService(db, queue, publisher=publisher), method)(task.id, world.org_b.id)
        assert caught.value.status_code == 404
    queue.cancel_task.assert_not_awaited()
    publisher.send_command_live.assert_not_awaited()


@pytest.mark.parametrize("method,initial", [
    ("cancel_task", TaskStatus.QUEUED), ("cancel_task", TaskStatus.ASSIGNED),
    ("force_stop_task", TaskStatus.QUEUED), ("force_stop_task", TaskStatus.RUNNING),
])
async def test_current_active_task_can_still_be_cancelled(world, method, initial):
    task = await seed_task(world, initial)
    async with world.sessions() as db:
        result = await getattr(TaskService(db, AsyncMock(), publisher=AsyncMock()), method)(task.id, world.org_a.id)
        await db.commit()
        assert result.status == TaskStatus.CANCELLED
