"""Bound device accounts stay in the exact application/server pool."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from backend.models.application_profile import ApplicationProfile
from backend.models.device import Device
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.pipeline import Pipeline, PipelineRun, PipelineRunStatus
from backend.models.task import Task
from backend.services.event_reactor import EventReactor
from backend.services.orchestrator.step_handlers import (
    handle_assign_account,
    handle_release_account,
)
from backend.services.task_service import TaskService


async def two_profiles(world):
    async with world.sessions() as db:
        first, second = [ApplicationProfile(
            org_id=world.org_a.id, key=key, name=key,
            servers=[{"key": "eu", "name": "EU", "domain": f"{key}.example.test", "port": 443}],
        ) for key in ("game-a", "game-b")]
        db.add_all([first, second])
        await db.flush()
        for device_id, profile in ((world.dev_a.id, first), (world.dev_a2.id, second)):
            device = await db.get(Device, device_id)
            device.application_profile_id = profile.id
            device.application_server_key = "eu"
        accounts = [GameAccount(
            org_id=world.org_a.id, game=game, login=login, server_name=server, password_encrypted="",
        ) for game, login, server in (
            ("game-a", "same_login", "EU"), ("game-b", "same_login", "EU"),
            ("game-a", "other_server", "NA"), ("game-a", "replacement", "EU"),
        )]
        db.add_all(accounts)
        await db.commit()
        return [item.id for item in accounts]


async def test_manual_assignment_and_task_admission_reject_different_profile_or_server(world):
    alpha, beta, wrong_server, _ = await two_profiles(world)
    api = world.client
    auth = world.auth(world.users["org_admin"])
    device_id = str(world.dev_a.id)
    for wrong_account in (beta, wrong_server):
        response = await api.post(f"/api/v1/game-accounts/{wrong_account}/assign", json={"device_id": device_id}, headers=auth)
        assert response.status_code == 409, response.text
        response = await api.post("/api/v1/tasks", json={
            "device_id": device_id, "script_id": str(world.script.id), "account_id": str(wrong_account),
        }, headers=auth)
        assert response.status_code == 409, response.text
    assigned = await api.post(f"/api/v1/game-accounts/{alpha}/assign", json={"device_id": device_id}, headers=auth)
    assert assigned.status_code == 200, assigned.text
    valid = await api.post("/api/v1/tasks", json={
        "device_id": device_id, "script_id": str(world.script.id), "account_id": str(alpha),
    }, headers=auth)
    assert valid.status_code == 201, valid.text
    async with world.sessions() as db:
        stored = await db.get(Task, uuid.UUID(valid.json()["id"]))
        assert stored.input_params["account_id"] == str(alpha)
        assert stored.script_version_id == world.version.id


async def test_bound_pipeline_assign_and_release_use_exact_account_scope_and_session(world):
    alpha, beta, wrong_server, replacement = await two_profiles(world)
    async with world.sessions() as db:
        pipeline = Pipeline(org_id=world.org_a.id, name="Scoped pipeline", steps=[], input_schema={})
        db.add(pipeline)
        await db.flush()
        run = PipelineRun(
            org_id=world.org_a.id, pipeline_id=pipeline.id, device_id=world.dev_a.id,
            status=PipelineRunStatus.RUNNING, steps_snapshot=[], context={},
        )
        db.add(run)
        await db.flush()
        for wrong_account in (beta, wrong_server):
            result = await handle_assign_account(
                {"id": "assign", "params": {"game": "game-a", "account_id": str(wrong_account)}}, run, db,
            )
            assert result.status == "failure"
        good = await handle_assign_account({"id": "assign", "params": {"game": "game-a"}}, run, db)
        assert good.status == "success" and good.output["account_id"] in {str(alpha), str(replacement)}
        run.context = good.context_updates
        await db.flush()
        release = await handle_release_account({"params": {}}, run, db)
        assert release.status == "success"
        selected = await db.get(GameAccount, uuid.UUID(good.output["account_id"]))
        assert selected.status == AccountStatus.free and selected.device_id is None
        assert (await db.get(GameAccount, beta)).device_id is None


async def test_bound_device_rotation_cannot_mutate_foreign_game_or_pick_wrong_server(world):
    alpha, beta, wrong_server, replacement = await two_profiles(world)
    async with world.sessions() as db:
        # Oldest candidates sort first. These two must never be selected.
        other = await db.get(GameAccount, beta)
        current = await db.get(GameAccount, alpha)
        current.device_id = world.dev_a.id
        current.status = AccountStatus.in_use
        current.assigned_at = datetime.now(timezone.utc)
        await db.flush()
        unrelated = await EventReactor(db).process_event(
            world.org_a.id, world.dev_a.id, "account.banned", account_id=beta,
        )
        assert unrelated.account_id is None and other.status == AccountStatus.free
        valid = await EventReactor(db).process_event(world.org_a.id, world.dev_a.id, "account.banned", account_id=alpha)
        assert valid.data["new_account_id"] == str(replacement)
        assert (await db.get(GameAccount, wrong_server)).device_id is None
        assert (await db.get(GameAccount, replacement)).device_id == world.dev_a.id
        assert current.status == AccountStatus.banned


async def test_dispatch_rechecks_bound_scope_when_account_server_changed_after_admission(world):
    alpha, _, _, _ = await two_profiles(world)
    async with world.sessions() as db:
        svc = TaskService(db)
        task = await svc.create_task(world.script.id, world.dev_a.id, world.org_a.id, account_id=alpha)
        account = await db.get(GameAccount, alpha)
        account.server_name = "NA"
        await db.commit()
        task_id = task.id
    async with world.sessions() as db:
        cache = AsyncMock()
        cache.bulk_get_status.side_effect = lambda ids: {key: SimpleNamespace(status="online") for key in ids}
        publisher = AsyncMock()
        await TaskService(db, status_cache=cache, publisher=publisher).dispatch_pending_tasks(org_id=world.org_a.id)
        publisher.send_command_live.assert_not_called()
        task = await db.scalar(select(Task).where(Task.id == task_id))
        assert task.status == "failed" and task.error_message == "Account does not match the device application and server"
