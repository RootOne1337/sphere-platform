"""Functional automation controls on a migrated, disposable PostgreSQL database."""
import asyncio
import json
import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import backend.models  # noqa: F401 - register SQLAlchemy relationships
from backend.models.account_session import AccountSession
from backend.models.device import Device
from backend.models.game_account import GameAccount
from backend.models.organization import Organization
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.schemas.game_accounts import AssignAccountRequest, ReleaseAccountRequest
from backend.services.game_account_service import GameAccountService
from backend.services.orchestrator.orchestration_engine import OrchestrationEngine
from backend.services.orchestrator.pipeline_recovery import OwnedPipelineRunner
from backend.services.orchestrator.step_handlers import StepHandlerRegistry
from backend.services.pipeline_settings_service import PipelineSettingsService
from backend.services.task_service import TaskService


async def make_script(db, org_id, name):
    script = Script(org_id=org_id, name=name)
    db.add(script)
    await db.flush()
    version = ScriptVersion(org_id=org_id, script_id=script.id, dag={"nodes": [], "entry_node": "start"})
    db.add(version)
    await db.flush()
    script.current_version_id = version.id
    return script


async def make_account(db, org_id, name, device_id=None):
    account = GameAccount(org_id=org_id, game="audit-game", login=name, status="free",
                          password_encrypted="synthetic", device_id=device_id, target_level=1)
    db.add(account)
    await db.flush()
    return account


async def farming_probe(sessions, org_id, device_a, device_b, old_script_id, new_script_id):
    orchestrator = OrchestrationEngine()
    async with sessions() as db:
        settings_service = PipelineSettingsService(db)
        settings = await settings_service.update(org_id, {"farming_script_id": old_script_id})
        account = await make_account(db, org_id, "config-change", device_a)
        await orchestrator._create_farming_task(db, settings, account)
        task = await db.scalar(select(Task).where(Task.device_id == device_a))
        assert task.status == TaskStatus.QUEUED
        await db.commit()
        settings = await settings_service.update(org_id, {"farming_script_id": new_script_id})
        task_service = TaskService(db)
        task_service.queue.mark_completed = AsyncMock()
        assert await task_service.handle_task_result(
            str(task.id), str(device_a), {"success": True, "level": 1}, str(org_id),
        )
        await db.commit()
        await orchestrator._process_completed_tasks(db, settings)
        await db.commit()
        await db.refresh(account)
        await db.refresh(task)
        assert account.status == "in_use" and task.orchestration_processed_at is None
        switched = {
            "account": account.status.value,
            "task": task.status.value,
            "accounted": task.orchestration_processed_at is not None,
        }
        settings = await settings_service.update(org_id, {"farming_script_id": old_script_id})
        await orchestrator._process_completed_tasks(db, settings)
        await db.commit()
        assert account.status == "free" and account.total_sessions == 1
        assert task.orchestration_processed_at is not None
        restored = {"account": account.status.value, "accounted": True}

        cancelled_account = await make_account(db, org_id, "cancelled-task", device_b)
        await orchestrator._create_farming_task(db, settings, cancelled_account)
        cancelled_task = await db.scalar(select(Task).where(Task.device_id == device_b))
        await TaskService(db).cancel_task(cancelled_task.id, org_id)
        await db.commit()
        await orchestrator._process_completed_tasks(db, settings)
        await db.commit()
        await db.refresh(cancelled_account)
        await db.refresh(cancelled_task)
        assert cancelled_account.status == "in_use" and cancelled_task.orchestration_processed_at is None
        cancelled = {
            "account": cancelled_account.status.value,
            "task": cancelled_task.status.value,
            "accounted": cancelled_task.orchestration_processed_at is not None,
        }
    return {"after_script_change": switched, "after_restoring_original_script": restored, "after_cancel": cancelled}


async def stale_release_probe(sessions, org_id, device_a, device_b):
    steps = [
        {"id": "assign", "type": "assign_account", "params": {"game": "audit-game"}, "on_success": "wait"},
        {"id": "wait", "type": "delay", "params": {"delay_ms": 100}, "on_success": "release"},
        {"id": "release", "type": "release_account", "params": {}},
    ]
    async with sessions() as db:
        account = await make_account(db, org_id, "pipeline-release")
        steps[0]["params"]["account_id"] = str(account.id)
        account_id = account.id
        pipeline = Pipeline(org_id=org_id, name="Account workflow", steps=steps)
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(org_id=org_id, pipeline_id=pipeline.id, device_id=device_a,
                          status=PipelineRunStatus.RUNNING, steps_snapshot=steps)
        db.add(run)
        await db.commit()
        run_id = run.id

    runner = OwnedPipelineRunner(uuid4(), sessions)
    entered_delay = asyncio.Event()
    resume_delay = asyncio.Event()
    original_delay = StepHandlerRegistry._handlers["delay"]

    async def synchronized_delay(step, run, db):
        entered_delay.set()
        await asyncio.wait_for(resume_delay.wait(), 5)
        return await original_delay(step, run, db)

    with patch.dict(StepHandlerRegistry._handlers, {"delay": synchronized_delay}):
        worker = asyncio.create_task(runner.run(run_id))
        try:
            await asyncio.wait_for(entered_delay.wait(), 5)
            async with sessions() as db:
                run = await db.get(PipelineRun, run_id)
                account = await db.get(GameAccount, account_id)
                session = await db.scalar(select(AccountSession).where(AccountSession.pipeline_run_id == run_id))
                assert run.status == PipelineRunStatus.RUNNING and run.current_step_id == "wait"
                assert account.device_id == device_a and session.ended_at is None
                session_id = session.id
                service = GameAccountService(db)
                await service.release_account(account_id, org_id, ReleaseAccountRequest())
                await service.assign_account(account_id, org_id, AssignAccountRequest(device_id=device_b))
                await db.commit()
                assert account.device_id == device_b and account.status == "in_use"
                previous_count = account.total_sessions
        finally:
            resume_delay.set()
            await asyncio.wait_for(worker, 5)
    async with sessions() as db:
        run = await db.get(PipelineRun, run_id)
        account = await db.get(GameAccount, account_id)
        session = await db.get(AccountSession, session_id)
        assert run.status == PipelineRunStatus.COMPLETED
        assert account.status == "free" and account.device_id is None
        assert account.total_sessions == previous_count + 1 and session.ended_at is not None
        assert await db.scalar(select(func.count(AccountSession.id)).where(
            AccountSession.account_id == account_id, AccountSession.device_id == device_b,
        )) == 0
        return {
            "before_stale_release": {"account": "in_use", "device": "B", "total_sessions": previous_count},
            "after_stale_release": {
                "account": account.status.value, "device": None, "total_sessions": account.total_sessions,
                "old_session_closed": session.ended_at is not None, "run": run.status.value,
            },
        }


async def main():
    url = make_url(os.environ["POSTGRES_URL"])
    if url.host not in {"127.0.0.1", "localhost", "::1"} or url.database != "sphere_automation_closure_audit":
        raise RuntimeError("Use the dedicated disposable automation closure database")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as db:
            org = Organization(name="Automation Audit", slug=f"automation-audit-{uuid4().hex}")
            db.add(org)
            await db.flush()
            a = Device(org_id=org.id, name="audit-device-a")
            b = Device(org_id=org.id, name="audit-device-b")
            db.add_all([a, b])
            old = await make_script(db, org.id, "Original farm script")
            new = await make_script(db, org.id, "New farm script")
            await db.commit()
        farming = await farming_probe(sessions, org.id, a.id, b.id, old.id, new.id)
        release = await stale_release_probe(sessions, org.id, a.id, b.id)
        print(json.dumps({"farming": farming, "release": release}, indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
