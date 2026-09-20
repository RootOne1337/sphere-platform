"""Disposable worker used by the OS-process-loss regression; never a deployment CLI."""

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager

from sqlalchemy.engine import make_url

url = make_url(os.environ["POSTGRES_URL"])
assert os.environ.get("SPHERE_RUN_INTEGRATION") == "1"
assert url.host in {"127.0.0.1", "localhost", "::1"} and "audit" in url.database
tenant = uuid.UUID(sys.argv[1])

from backend.models.pipeline import PipelineRun  # noqa: E402
from backend.services.orchestrator import pipeline_executor  # noqa: E402

sessions = pipeline_executor.AsyncSessionLocal


@asynccontextmanager
async def scoped_sessions():
    async with sessions() as db:
        execute = db.execute

        async def scoped(statement, *args, **kwargs):
            if any(d.get("entity") is PipelineRun
                   for d in getattr(statement, "column_descriptions", [])):
                statement = statement.where(PipelineRun.org_id == tenant)
            return await execute(statement, *args, **kwargs)

        db.execute = scoped
        yield db


pipeline_executor.AsyncSessionLocal = scoped_sessions
asyncio.run(pipeline_executor.PipelineExecutor().start())
