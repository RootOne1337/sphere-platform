"""Historical F32-25 reproduction on source 6ebca1b, before AUD-133.

Run explicitly with disposable loopback PostgreSQL/Redis and SPHERE_RUN_INTEGRATION=1.
Retained as original evidence, not a current passing test or rollout check.
Current regressions: tests/production/test_pipeline_rls.py (includes discovery grant).
Without that grant this historical probe cannot exercise the new worker contract.
"""

import asyncio

import pytest
from sqlalchemy import select

from backend.models.pipeline import PipelineRun, PipelineRunStatus
from backend.services.orchestrator.pipeline_executor import PipelineExecutor
from tests.production.conftest import runtime_db, world  # noqa: F401 — pytest fixtures
from tests.production.test_pipeline_recovery import seed


@pytest.mark.asyncio
async def test_unscoped_pipeline_worker_can_claim_its_persisted_run(runtime_db, monkeypatch):  # noqa: F811
    r = runtime_db
    run = await seed(r.world, status=PipelineRunStatus.QUEUED)
    monkeypatch.setattr("backend.services.orchestrator.pipeline_executor.AsyncSessionLocal", r.sessions)
    executor = PipelineExecutor()
    try:
        await executor._poll_and_dispatch()
        async with r.world.sessions() as db:
            status = await db.scalar(select(PipelineRun.status).where(PipelineRun.id == run.id))
        assert status == PipelineRunStatus.RUNNING, f"unscoped RLS worker left run {status}"
    finally:
        jobs = list(executor._tasks)
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
