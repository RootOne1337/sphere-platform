"""Every task producer must retain version, tenant and execution authority."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from backend.models.game_account import GameAccount
from backend.models.task import Task
from backend.services.orchestrator.orchestration_engine import OrchestrationEngine


async def test_registration_without_script_does_not_persist_account(world, account_credential_key):
    w = world
    async with w.sessions() as db:
        config = SimpleNamespace(org_id=w.org_a.id, registration_script_id=None,
                                 nick_generation_enabled=False, default_target_level=1,
                                 registration_timeout_seconds=300)
        with pytest.raises(ValueError, match="Registration script is required"):
            await OrchestrationEngine()._create_registration_task(db, config, w.dev_a)
        assert await db.scalar(select(func.count()).select_from(GameAccount).where(
            GameAccount.org_id == w.org_a.id,
        )) == 0
        assert await db.scalar(select(func.count()).select_from(Task).where(
            Task.org_id == w.org_a.id,
        )) == 0


@pytest.mark.parametrize("missing", ["device", "script"])
async def test_farming_requires_device_and_script_before_mutating_account(world, missing):
    w = world
    async with w.sessions() as db:
        account = GameAccount(org_id=w.org_a.id, device_id=None if missing == "device" else w.dev_a.id,
                              game="audit", login="precondition", status="free",
                              password_encrypted="synthetic-password")
        db.add(account)
        await db.flush()
        config = SimpleNamespace(org_id=w.org_a.id,
                                 farming_script_id=None if missing == "script" else w.script.id)
        with pytest.raises(ValueError, match="Farming requires a device and script"):
            await OrchestrationEngine()._create_farming_task(db, config, account)
        assert account.status == "free"
        assert await db.scalar(select(func.count()).select_from(Task).where(
            Task.org_id == w.org_a.id,
        )) == 0


async def test_farming_task_has_version_without_redis_publication(world):
    w = world
    async with w.sessions() as db:
        account = GameAccount(org_id=w.org_a.id, device_id=w.dev_a.id, game="audit",
                              login="audit-login", password_encrypted="synthetic-password")
        db.add(account)
        await db.flush()
        config = SimpleNamespace(org_id=w.org_a.id, farming_script_id=w.script.id,
                                  farming_session_duration_seconds=300)
        with patch("backend.database.redis_client.redis_binary", w.redis):
            await OrchestrationEngine()._create_farming_task(db, config, account)
        task = await db.scalar(select(Task).where(Task.device_id == w.dev_a.id))
        assert task.script_version_id == w.version.id
        assert "password" not in task.input_params
        await db.rollback()
    assert await w.redis.zcard(f"task_queue:{w.org_a.id}:{w.dev_a.id}") == 0


async def test_n8n_viewer_cannot_execute_a_task(world):
    w = world
    response = await w.client.post("/api/v1/n8n/tasks", headers=w.auth(w.users["viewer"]),
        json={"device_id": str(w.dev_a.id), "script_id": str(w.script.id)})
    assert response.status_code == 403


async def test_n8n_valid_task_pins_current_version_and_rejects_foreign_device(world):
    w = world
    headers = w.auth(w.users["org_admin"])
    response = await w.client.post("/api/v1/n8n/tasks", headers=headers,
        json={"device_id": str(w.dev_b.id), "script_id": str(w.script.id)})
    assert response.status_code == 404
    response = await w.client.post("/api/v1/n8n/tasks", headers=headers,
        json={"device_id": str(w.dev_a.id), "script_id": str(w.script.id)})
    assert response.status_code == 201, response.text
    async with w.sessions() as db:
        task = await db.scalar(select(Task).where(Task.device_id == w.dev_a.id))
        assert task.script_version_id == w.version.id
