"""Security policy regressions using real local PostgreSQL, Redis and JWT authentication."""

import pytest

from backend.models.game_account import GameAccount
from backend.models.task import Task, TaskStatus
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService


@pytest.mark.asyncio
async def test_F06_agent_can_complete_foreign_org_task(world):
    w = world
    async with w.sessions() as db:
        task = Task(
            org_id=w.org_b.id,
            device_id=w.dev_b.id,
            script_id=w.script.id,
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.commit()
        queue = TaskQueue(w.redis)
        await TaskService(db, queue).handle_task_result(
            str(task.id), str(w.dev_a.id), {"success": True, "audit_marker": "forged"}
        )
        await db.commit()
        assert task.status == TaskStatus.RUNNING
        assert task.result is None


@pytest.mark.asyncio
async def test_F07_foreign_account_credentials_inserted_into_dag(world):
    w = world
    async with w.sessions() as db:
        foreign_account = GameAccount(
            org_id=w.org_b.id,
            game="audit",
            login="foreign-login",
            password_encrypted="foreign-password-marker",
        )
        db.add(foreign_account)
        await db.flush()
        task = Task(
            org_id=w.org_a.id,
            device_id=w.dev_a.id,
            script_id=w.script.id,
            input_params={"account_id": str(foreign_account.id)},
        )
        svc = TaskService(db, TaskQueue(w.redis))
        account = await svc._load_account_for_task(task)
        assert account is None


@pytest.mark.asyncio
async def test_device_result_is_idempotent(world):
    w = world
    async with w.sessions() as db:
        task = Task(
            org_id=w.org_a.id,
            device_id=w.dev_a.id,
            script_id=w.script.id,
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.commit()
        svc = TaskService(db, TaskQueue(w.redis))
        await svc.handle_task_result(
            str(task.id), str(w.dev_a.id), {"success": True, "value": "first"}
        )
        await db.commit()
        await svc.handle_task_result(
            str(task.id), str(w.dev_a.id), {"success": False, "value": "duplicate"}
        )
        await db.commit()
        assert task.status == TaskStatus.COMPLETED
        assert task.result == {"success": True, "value": "first"}
