"""Expected baseline failure at d859a52; only disposable test database writes."""

import asyncio
import json

from sqlalchemy import select

from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor
from tests.production.test_pipeline_admission import cleanup


async def test_nested_runs_progress_when_all_worker_slots_are_waiting(world, monkeypatch):
    async with world.sessions() as db:
        child = Pipeline(org_id=world.org_a.id, name="nested-capacity-empty-child", steps=[])
        parent = Pipeline(org_id=world.org_a.id, name="nested-capacity-parent")
        db.add_all([child, parent])
        await db.flush()
        parents = [PipelineRun(
            org_id=world.org_a.id, pipeline_id=parent.id, device_id=world.dev_a.id,
            status=PipelineRunStatus.QUEUED, steps_snapshot=[{
                "id": "nested", "type": "sub_pipeline", "timeout_ms": 60000,
                "params": {"pipeline_id": str(child.id)},
            }],
        ) for _ in range(10)]
        db.add_all(parents)
        await db.commit()
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", world.sessions)
    executor = PipelineExecutor()

    async def state():
        async with world.sessions() as db:
            rows = list(await db.scalars(select(PipelineRun).where(PipelineRun.org_id == world.org_a.id)))
            return {
                "active_coroutines": len(executor._tasks),
                "parents_running": sum(r.pipeline_id == parent.id and r.status == PipelineRunStatus.RUNNING for r in rows),
                "children_queued": sum(r.pipeline_id == child.id and r.status == PipelineRunStatus.QUEUED for r in rows),
                "parents_completed": sum(r.pipeline_id == parent.id and r.status == PipelineRunStatus.COMPLETED for r in rows),
            }

    try:
        await executor._poll_and_dispatch(org_id=world.org_a.id)
        async def all_children_created():
            while (await state())["children_queued"] != 10:
                await asyncio.sleep(0.02)
        await asyncio.wait_for(all_children_created(), 8)
        initial = await state()
        for _ in range(8):
            await executor._poll_and_dispatch(org_id=world.org_a.id)
            await asyncio.sleep(0.1)
        final = await state()
        print(json.dumps({"before_polls": initial, "after_eight_polls": final}))
        assert final["parents_completed"] > 0, "Waiting parents occupy all slots; even empty children remain queued"
    finally:
        await cleanup(executor)
