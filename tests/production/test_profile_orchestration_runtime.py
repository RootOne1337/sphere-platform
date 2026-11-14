"""Profile AUTO work through migrated PostgreSQL and the ordinary worker role."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.models.application_automation_policy import ApplicationAutomationPolicy
from backend.models.application_profile import ApplicationProfile
from backend.models.device import Device
from backend.models.game_account import AccountStatus, GameAccount
from backend.models.pipeline_settings import PipelineSettings
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.services.orchestrator import orchestration_engine
from backend.services.orchestrator.orchestration_engine import OrchestrationEngine
from backend.services.task_service import TaskService


def _profile(org_id, key):
    return ApplicationProfile(
        org_id=org_id, key=key, name=key.title(), android_package=f"test.example.{key}",
        servers=[
            {"key": "shared", "name": "Shared", "domain": "shared.example.test", "port": 9001},
            {"key": "different", "name": "Different", "domain": "different.example.test", "port": 9002},
        ],
    )


def _policy(profile, script_id, *, register=False, farm=False, cooldown=13):
    return ApplicationAutomationPolicy(
        org_id=profile.org_id, application_profile_id=profile.id, revision=1,
        registration_enabled=register, registration_script_id=script_id,
        max_concurrent_registrations=1, registration_timeout_seconds=600,
        farming_enabled=farm, farming_script_id=script_id, max_concurrent_farming=1,
        farming_session_duration_seconds=1800, default_target_level=7, cooldown_between_sessions_minutes=cooldown,
    )


def _account(device, game, *, server="Shared", status=AccountStatus.free):
    now = datetime.now(timezone.utc)
    return GameAccount(
        org_id=device.org_id, device_id=device.id, game=game, server_name=server,
        login=f"fixture-{game}-{server}", password_encrypted="fixture-only", status=status,
        assigned_at=now, status_changed_at=now, level=1, target_level=7,
    )


@pytest_asyncio.fixture
async def worker(world, runtime_db, monkeypatch):
    async with world.engine.begin() as db:
        await db.execute(text(
            f'GRANT EXECUTE ON FUNCTION sphere_auth.orchestration_work(uuid) TO "{runtime_db.role}"'
        ))
    engine = create_async_engine(runtime_db.engine.url, pool_size=2, max_overflow=0)
    monkeypatch.setattr(orchestration_engine, "AsyncSessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    try:
        yield OrchestrationEngine()
    finally:
        await engine.dispose()
        async with world.engine.begin() as db:
            await db.execute(text(
                f'REVOKE EXECUTE ON FUNCTION sphere_auth.orchestration_work(uuid) FROM "{runtime_db.role}"'
            ))


async def _tasks(db, world):
    return (await db.scalars(select(Task).where(Task.org_id == world.org_a.id)
                             .order_by(Task.created_at, Task.id))).all()


async def test_profiles_select_exact_pools_and_reconcile_after_settings_and_version_change(
    world, worker, account_credential_key,
):
    async with world.sessions() as db:
        alpha, beta, foreign = (_profile(world.org_a.id, "alpha"), _profile(world.org_a.id, "beta"),
                                _profile(world.org_b.id, "alpha"))
        db.add_all([alpha, beta, foreign])
        await db.flush()
        alpha_policy = _policy(alpha, world.script.id, register=True)
        beta_policy = _policy(beta, world.script.id, farm=True)
        db.add_all([alpha_policy, beta_policy])
        dev_alpha = await db.get(Device, world.dev_a.id)
        dev_beta = await db.get(Device, world.dev_a2.id)
        dev_alpha.application_profile_id = alpha.id
        dev_beta.application_profile_id = beta.id
        dev_alpha.application_server_key = dev_beta.application_server_key = "shared"
        dev_alpha.server_name = dev_beta.server_name = "Legacy Unrelated"
        wrong_game = _account(dev_beta, "alpha")
        wrong_server = _account(dev_beta, "beta", server="Different")
        correct = _account(dev_beta, "beta")
        db.add_all([wrong_game, wrong_server, correct])
        await db.commit()

    await worker._tick()
    async with world.sessions() as db:
        tasks = await _tasks(db, world)
        assert len(tasks) == 2
        register = next(task for task in tasks if task.orchestration_kind == "register")
        farm = next(task for task in tasks if task.orchestration_kind == "farm")
        assert register.orchestration_profile_id == alpha.id
        assert farm.orchestration_profile_id == beta.id
        assert register.device_id == dev_alpha.id
        assert farm.device_id == dev_beta.id
        assert farm.input_params["account_id"] == str(correct.id)
        assert register.script_version_id == farm.script_version_id == world.version.id
        assert register.timeout_seconds == 600 and farm.timeout_seconds == 1800
        registered = await db.get(GameAccount, register.input_params["account_id"])
        assert (registered.game, registered.server_name, registered.target_level) == ("alpha", "Shared", 7)
        assert (await db.get(GameAccount, wrong_game.id)).status == AccountStatus.free
        assert (await db.get(GameAccount, wrong_server.id)).status == AccountStatus.free

        script = await db.get(Script, world.script.id)
        latest = ScriptVersion(org_id=world.org_a.id, script_id=script.id, version=2,
                               dag={"nodes": [], "entry_node": "start"})
        db.add(latest)
        await db.flush()
        script.current_version_id = latest.id
        db_alpha = await db.get(ApplicationAutomationPolicy, (world.org_a.id, alpha.id))
        db_beta = await db.get(ApplicationAutomationPolicy, (world.org_a.id, beta.id))
        db_alpha.registration_enabled = False
        db_alpha.registration_script_id = None
        db_beta.farming_enabled = False
        db_beta.farming_script_id = None
        db_beta.cooldown_between_sessions_minutes = 77
        register.status, register.result = TaskStatus.COMPLETED, {"success": True}
        farm.status, farm.result = TaskStatus.COMPLETED, {"level": 3}
        await db.commit()

    # Only pending receipts discover this tenant after both policies are disabled.
    await worker._tick()
    await worker._tick()
    async with world.sessions() as db:
        tasks = await _tasks(db, world)
        assert len(tasks) == 2
        assert all(task.orchestration_processed_at is not None for task in tasks)
        assert all(task.script_version_id == world.version.id for task in tasks)
        assert all(task.status == TaskStatus.COMPLETED for task in tasks)
        farmed = await db.get(GameAccount, correct.id)
        assert (farmed.level, farmed.status, farmed.total_sessions) == (3, AccountStatus.cooldown, 1)
        assert farmed.cooldown_until - farmed.last_session_end == timedelta(minutes=13)
        assert (await db.get(GameAccount, registered.id)).status == AccountStatus.free


async def test_registration_ban_receipt_does_not_mark_account_registered(world, worker, account_credential_key):
    async with world.sessions() as db:
        profile = _profile(world.org_a.id, "alpha")
        db.add(profile)
        await db.flush()
        policy = _policy(profile, world.script.id, register=True)
        db.add(policy)
        device = await db.get(Device, world.dev_a.id)
        device.application_profile_id = profile.id
        device.application_server_key = "shared"
        await db.commit()

    await worker._tick()
    async with world.sessions() as db:
        [task] = await _tasks(db, world)
        account_id = task.input_params["account_id"]
        task.status = TaskStatus.COMPLETED
        task.result = {"success": True, "ban_detected": True}
        policy = await db.get(ApplicationAutomationPolicy, (world.org_a.id, profile.id))
        policy.registration_enabled = False
        await db.commit()

    await worker._tick()
    await worker._tick()
    async with world.sessions() as db:
        account = await db.get(GameAccount, account_id)
        assert (account.status, account.total_bans, account.registered_at) == (AccountStatus.banned, 1, None)
        [task] = await _tasks(db, world)
        assert task.orchestration_processed_at is not None


async def test_ban_replacement_and_terminal_receipt_keep_exact_assignment(
    world, worker, account_credential_key,
):
    async with world.sessions() as db:
        alpha, beta = _profile(world.org_a.id, "alpha"), _profile(world.org_a.id, "beta")
        db.add_all([alpha, beta])
        await db.flush()
        db.add_all([
            _policy(alpha, world.script.id, register=True, farm=True),
            _policy(beta, world.script.id, register=True),
            PipelineSettings(org_id=world.org_a.id, orchestration_enabled=False,
                             auto_replace_banned=True, ban_detection_enabled=True),
        ])
        dev_alpha = await db.get(Device, world.dev_a.id)
        dev_beta = await db.get(Device, world.dev_a2.id)
        dev_alpha.application_profile_id, dev_beta.application_profile_id = alpha.id, beta.id
        dev_alpha.application_server_key = dev_beta.application_server_key = "shared"
        banned = _account(dev_alpha, "alpha", status=AccountStatus.banned)
        wrong = _account(dev_alpha, "beta", status=AccountStatus.banned)
        wrong_server = _account(dev_alpha, "alpha", server="Different", status=AccountStatus.banned)
        db.add_all([banned, wrong, wrong_server])
        await db.commit()

    await worker._tick()
    async with world.sessions() as db:
        tasks = await _tasks(db, world)
        assert len(tasks) == 2
        assert all(task.orchestration_kind == "register" for task in tasks)
        assert (await db.get(GameAccount, banned.id)).device_id is None
        assert (await db.get(GameAccount, wrong.id)).device_id == dev_alpha.id
        assert (await db.get(GameAccount, wrong_server.id)).device_id == dev_alpha.id
        register = next(task for task in tasks if task.device_id == dev_alpha.id)
        beta_task = next(task for task in tasks if task.device_id == dev_beta.id)
        replacement = await db.get(GameAccount, register.input_params["account_id"])
        assert (replacement.game, replacement.server_name) == ("alpha", "Shared")
        register.status = TaskStatus.COMPLETED
        register.result = {"success": True}
        beta_task.status = TaskStatus.CANCELLED
        beta_policy = await db.get(ApplicationAutomationPolicy, (world.org_a.id, beta.id))
        beta_policy.registration_enabled = False
        await db.commit()

    await worker._tick()
    async with world.sessions() as db:
        tasks = await _tasks(db, world)
        assert len(tasks) == 3
        farm = next(task for task in tasks if task.orchestration_kind == "farm")
        account = await db.get(GameAccount, replacement.id)
        assert farm.input_params["account_id"] == str(account.id)
        assert (await db.get(GameAccount, beta_task.input_params["account_id"])).status == AccountStatus.disabled
        account.assigned_at += timedelta(seconds=1)
        farm.status, farm.result = TaskStatus.COMPLETED, {"level": 6, "ban_detected": True}
        await db.commit()

    await worker._tick()
    async with world.sessions() as db:
        refreshed = await db.get(GameAccount, replacement.id)
        assert (refreshed.status, refreshed.level, refreshed.total_sessions) == (AccountStatus.in_use, None, 0)
        assert (await db.get(Task, farm.id)).orchestration_processed_at is not None


async def test_concurrent_workers_cannot_overbook_profiles(
    world, worker, account_credential_key,
):
    second_worker = OrchestrationEngine()
    async with world.sessions() as db:
        profile = _profile(world.org_a.id, "alpha")
        db.add(profile)
        await db.flush()
        db.add(_policy(profile, world.script.id, register=True))
        for device_id in (world.dev_a.id, world.dev_a2.id):
            device = await db.get(Device, device_id)
            device.application_profile_id = profile.id
            device.application_server_key = "shared"
        await db.commit()

    await asyncio.gather(worker._tick(), second_worker._tick())
    async with world.sessions() as db:
        tasks = await _tasks(db, world)
        assert len(tasks) == 1
        assert tasks[0].orchestration_profile_id == profile.id


async def test_failed_admission_rolls_back_new_account_and_preserves_other_profiles(
    world, worker, monkeypatch, account_credential_key,
):
    async with world.sessions() as db:
        alpha, beta = _profile(world.org_a.id, "alpha"), _profile(world.org_a.id, "beta")
        db.add_all([alpha, beta])
        await db.flush()
        db.add_all([_policy(alpha, world.script.id, register=True), _policy(beta, world.script.id, register=True)])
        for device_id, profile in ((world.dev_a.id, alpha), (world.dev_a2.id, beta)):
            device = await db.get(Device, device_id)
            device.application_profile_id = profile.id
            device.application_server_key = "shared"
        await db.commit()

    create_task = TaskService.create_task

    async def conflict_on_alpha(service, **kwargs):
        if kwargs["device_id"] == world.dev_a.id:
            raise HTTPException(409, "Fixture admission conflict")
        return await create_task(service, **kwargs)

    monkeypatch.setattr(TaskService, "create_task", conflict_on_alpha)
    await worker._tick()
    async with world.sessions() as db:
        tasks = await _tasks(db, world)
        assert len(tasks) == 1 and tasks[0].orchestration_profile_id == beta.id
        games = (await db.scalars(select(GameAccount.game).where(GameAccount.org_id == world.org_a.id))).all()
        assert games == ["beta"]


async def test_legacy_status_and_reconciliation_keep_untagged_tasks(world, worker):
    async with world.sessions() as db:
        profile = _profile(world.org_a.id, "alpha")
        db.add(profile)
        await db.flush()
        bound = await db.get(Device, world.dev_a2.id)
        bound.application_profile_id, bound.application_server_key = profile.id, "shared"
        bound.server_name = "Stale Legacy Label"
        legacy = await db.get(Device, world.dev_a.id)
        legacy.server_name = "Legacy Server"
        old = _account(legacy, "legacy", status=AccountStatus.in_use)
        managed = _account(bound, "alpha")
        legacy_free = _account(legacy, "old-value", server="Another")
        db.add_all([old, managed, legacy_free, PipelineSettings(
            org_id=world.org_a.id, orchestration_enabled=True,
            registration_script_id=world.script.id, farming_script_id=world.script.id,
        )])
        await db.flush()
        old_result = Task(
            org_id=world.org_a.id, device_id=legacy.id, script_id=world.script.id,
            status=TaskStatus.COMPLETED, result={"level": 7}, input_params={"account_id": str(old.id)},
        )
        shared = {"org_id": world.org_a.id, "device_id": legacy.id, "script_id": world.script.id,
                  "status": TaskStatus.QUEUED}
        db.add_all([
            old_result, Task(**shared), Task(**shared, orchestration_kind="register"),
            Task(**{**shared, "device_id": bound.id}, orchestration_kind="farm",
                 orchestration_profile_id=profile.id, orchestration_cooldown_minutes=30),
        ])
        await db.commit()

    response = await world.client.get("/api/v1/pipeline-settings/status", headers=world.auth(world.users["org_admin"]))
    assert response.status_code == 200, response.text
    status = response.json()
    assert (status["active_registrations"], status["active_farming_sessions"]) == (2, 1)
    assert (status["total_devices_with_server"], status["total_free_accounts"]) == (1, 1)

    await worker._tick()
    async with world.sessions() as db:
        assert (await db.get(Task, old_result.id)).orchestration_processed_at is not None
        account = await db.get(GameAccount, old.id)
        assert (account.status, account.total_sessions) == (AccountStatus.free, 1)
