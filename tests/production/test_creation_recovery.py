"""Retries must not replace durable work during disconnects or concurrent requests."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


async def test_concurrent_creators_cannot_enqueue_the_same_device_version_twice(world):
    w = world
    async with w.sessions() as first:
        created = await TaskService(first).create_task(w.script.id, w.dev_a.id, w.org_a.id)

        async def second_request():
            async with w.sessions() as second:
                try:
                    await TaskService(second).create_task(w.script.id, w.dev_a.id, w.org_a.id)
                    await second.commit()
                    return 201
                except HTTPException as exc:
                    await second.rollback()
                    return exc.status_code

        concurrent = asyncio.create_task(second_request())
        try:
            # First transaction remains open while the other creator attempts its insert.
            await asyncio.wait({concurrent}, timeout=0.15)
            await first.commit()
            assert await asyncio.wait_for(concurrent, 3) == 409
        finally:
            concurrent.cancel()
            await asyncio.gather(concurrent, return_exceptions=True)
        assert await first.scalar(select(func.count()).select_from(Task).where(
            Task.device_id == w.dev_a.id,
            Task.script_version_id == w.version.id,
            Task.status == TaskStatus.QUEUED,
        )) == 1
        assert (await first.get(Task, created.id)).status == TaskStatus.QUEUED


@pytest.mark.parametrize("status", [TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_missing_presence_cannot_replace_work_that_may_still_execute(world, status):
    w = world
    async with w.sessions() as db:
        task = await TaskService(db).create_task(w.script.id, w.dev_a.id, w.org_a.id)
        task.status = status
        await db.commit()
        cache = AsyncMock()
        cache.get_status.return_value = None  # Redis eviction or temporarily disconnected APK.
        with pytest.raises(HTTPException) as caught:
            await TaskService(db, status_cache=cache).create_task(w.script.id, w.dev_a.id, w.org_a.id)
        assert caught.value.status_code == 409
        await db.commit()
        await db.refresh(task)
        assert task.status == status
        assert task.finished_at is None


async def test_old_receipt_does_not_prove_execution_stopped(world):
    w = world
    async with w.sessions() as db:
        task = await TaskService(db).create_task(w.script.id, w.dev_a.id, w.org_a.id)
        task.status = TaskStatus.RUNNING
        task.updated_at = datetime.now(timezone.utc) - timedelta(hours=25)
        await db.commit()
        with pytest.raises(HTTPException) as caught:
            await TaskService(db).create_task(w.script.id, w.dev_a.id, w.org_a.id)
        assert caught.value.status_code == 409
        await db.commit()
        await db.refresh(task)
        assert task.status == TaskStatus.RUNNING
