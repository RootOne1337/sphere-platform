"""Background wave admission must see a committed parent and never escape failure."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.v1.batches.router import start_batch
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch
from backend.schemas.batch import BatchExecutionRequest
from backend.services.batch_service import BatchService


@pytest.fixture
def launches(monkeypatch):
    started = []
    create = asyncio.create_task

    def capture(coro, **kwargs):
        task = create(coro, **kwargs)
        if str(kwargs.get("name", "")).startswith("batch_waves_"):
            started.append(task)
        return task

    monkeypatch.setattr("backend.services.batch_service.asyncio.create_task", capture)
    return started


def request(world):
    return BatchExecutionRequest(script_id=world.script.id, device_ids=[world.dev_a.id],
                                 wave_delay_ms=0, jitter_ms=0, stagger_by_workstation=False)


async def test_background_worker_observes_committed_parent_without_caller_commit(world, launches, monkeypatch):
    observed = []

    async def inspect_parent(service, batch_id, *args):
        async with world.sessions() as observer:
            observed.append(await observer.scalar(select(TaskBatch.id).where(TaskBatch.id == batch_id)))

    monkeypatch.setattr(BatchService, "_execute_waves", inspect_parent)
    async with world.sessions() as db:
        batch = await BatchService(db, world.sessions).start_batch(
            request(world), world.org_a.id, world.users["org_admin"].id,
        )
        await asyncio.wait_for(asyncio.gather(*launches), 3)
        assert observed == [batch.id]
    async with world.sessions() as db:
        assert await db.get(TaskBatch, batch.id) is not None


async def test_commit_failure_does_not_launch_background_work(world, launches, monkeypatch):
    worker = AsyncMock()
    monkeypatch.setattr(BatchService, "_execute_waves", worker)
    async with world.sessions() as db:
        db.commit = AsyncMock(side_effect=RuntimeError("isolated injected commit failure"))
        try:
            with pytest.raises(RuntimeError, match="injected commit failure"):
                await start_batch(
                    request(world), current_user=world.users["org_admin"],
                    svc=BatchService(db, world.sessions), db=db,
                )
        finally:
            await asyncio.gather(*launches, return_exceptions=True)
        assert launches == []
        worker.assert_not_awaited()


async def test_wave_mapping_failure_does_not_commit_or_launch(world, launches, monkeypatch):
    monkeypatch.setattr("backend.services.batch_service.WorkstationMappingService.create_waves",
                        AsyncMock(side_effect=RuntimeError("isolated mapping failure")))
    async with world.sessions() as db:
        db.commit = AsyncMock(wraps=db.commit)
        with pytest.raises(RuntimeError, match="mapping failure"):
            await BatchService(db, world.sessions).start_batch(
                request(world), world.org_a.id, world.users["org_admin"].id,
            )
        db.commit.assert_not_awaited()
        assert launches == []


async def test_http_batch_start_commits_and_admits_real_task(world, launches, monkeypatch):
    monkeypatch.setattr("backend.api.v1.batches.router.AsyncSessionLocal", world.sessions)
    response = await world.client.post(
        "/api/v1/batches", headers=world.auth(world.users["org_admin"]),
        json=request(world).model_dump(mode="json"),
    )
    assert response.status_code == 202, response.text
    assert len(launches) == 1
    await asyncio.wait_for(asyncio.gather(*launches), 3)
    async with world.sessions() as db:
        task = await db.scalar(select(Task).where(Task.batch_id == response.json()["id"]))
        assert task is not None
        assert (task.device_id, task.status) == (world.dev_a.id, TaskStatus.QUEUED)
