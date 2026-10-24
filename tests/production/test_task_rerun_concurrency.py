"""Real PostgreSQL row locks serialize competing reruns through commit."""
import asyncio

from fastapi import HTTPException
from sqlalchemy import select

from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


async def test_simultaneous_reruns_queue_exactly_one_pinned_execution(world):
    async with world.sessions() as db:
        source = Task(org_id=world.org_a.id, device_id=world.dev_a.id,
                      script_id=world.script.id, script_version_id=world.version.id,
                      status=TaskStatus.FAILED, priority=3, timeout_seconds=91,
                      input_params={"priority": 3, "custom": {"region": "eu"}})
        db.add(source)
        await db.commit()

    async def rerun():
        async with world.sessions() as db:
            try:
                task = await TaskService(db).rerun_task(source.id, world.org_a.id)
                await db.commit()
                return task.id
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    first, second = await asyncio.wait_for(asyncio.gather(rerun(), rerun()), timeout=10)
    assert (first == 409) != (second == 409)
    async with world.sessions() as db:
        tasks = list(await db.scalars(select(Task).where(Task.device_id == world.dev_a.id)))
        assert len(tasks) == 2
        created = next(task for task in tasks if task.id != source.id)
        assert created.script_version_id == source.script_version_id
        assert created.input_params == source.input_params
        assert created.timeout_seconds == 91
        assert created.status == TaskStatus.QUEUED
