"""Orchestration accounting must preserve terminal outcomes and tenant ownership."""

import asyncio
from types import SimpleNamespace

from sqlalchemy import select

from backend.models.game_account import GameAccount
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator.orchestration_engine import OrchestrationEngine


def settings(world):
    return SimpleNamespace(org_id=world.org_a.id, registration_script_id=None,
        farming_script_id=world.script.id, cooldown_between_sessions_minutes=1)


async def test_accounting_preserves_terminal_task_and_runs_once(world):
    w = world
    async with w.sessions() as db:
        account = GameAccount(org_id=w.org_a.id, device_id=w.dev_a.id, game="audit",
            login="fixture", password_encrypted="synthetic", status="in_use", target_level=1)
        db.add(account)
        await db.flush()
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
            status=TaskStatus.COMPLETED, input_params={"account_id": str(account.id)},
            result={"success": True, "level": 1})
        db.add(task)
        await db.commit()
        await OrchestrationEngine()._process_completed_tasks(db, settings(w))
        await db.commit()
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"success": True, "level": 1}
        assert account.total_sessions == 1
        # Simulate the next farming session starting before the next engine tick.
        account.status = "in_use"
        await db.commit()
        await OrchestrationEngine()._process_completed_tasks(db, settings(w))
        await db.commit()
        assert account.total_sessions == 1
        assert account.status == "in_use"


async def test_task_cannot_update_an_account_in_another_organization(world):
    w = world
    async with w.sessions() as db:
        account = GameAccount(org_id=w.org_b.id, device_id=w.dev_b.id, game="audit",
            login="foreign-fixture", password_encrypted="synthetic", status="in_use", target_level=1)
        db.add(account)
        await db.flush()
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
            status=TaskStatus.COMPLETED, input_params={"account_id": str(account.id)},
            result={"success": True, "level": 99})
        db.add(task)
        await db.commit()
        await OrchestrationEngine()._process_completed_tasks(db, settings(w))
        await db.commit()
        assert account.status == "in_use"
        assert account.total_sessions == 0
        assert account.level != 99


async def test_another_worker_skips_locked_result_then_rollback_allows_retry(world):
    w = world
    async with w.sessions() as db:
        account = GameAccount(org_id=w.org_a.id, device_id=w.dev_a.id, game="audit",
            login="concurrent-fixture", password_encrypted="synthetic", status="in_use", target_level=1)
        db.add(account)
        await db.flush()
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
            status=TaskStatus.COMPLETED, input_params={"account_id": str(account.id)},
            result={"success": True, "level": 1})
        db.add(task)
        await db.commit()
    async with w.sessions() as owner:
        await owner.scalar(select(Task).where(Task.id == task.id).with_for_update())
        async with w.sessions() as other:
            await asyncio.wait_for(OrchestrationEngine()._process_completed_tasks(other, settings(w)), 1)
            await other.commit()
        await owner.rollback()
    async with w.sessions() as db:
        await OrchestrationEngine()._process_completed_tasks(db, settings(w))
        await db.rollback()
        assert (await db.get(Task, task.id)).orchestration_processed_at is None
        assert (await db.get(GameAccount, account.id)).total_sessions == 0
        await OrchestrationEngine()._process_completed_tasks(db, settings(w))
        await db.commit()
        assert (await db.get(Task, task.id)).status == TaskStatus.COMPLETED
        assert (await db.get(GameAccount, account.id)).total_sessions == 1
