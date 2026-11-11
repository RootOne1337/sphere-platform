"""Run production lifespan, valid HTTP and one worker control on disposable services."""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from secrets import token_hex
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def require_local_services():
    owner_url = make_url(os.environ["POSTGRES_URL"])
    redis = urlparse(os.environ["REDIS_URL"])
    if (
        os.environ.get("SPHERE_RUN_INTEGRATION") != "1"
        or owner_url.database != "sphere_audit_20261111"
        or owner_url.host != "127.0.0.1"
        or redis.hostname != "127.0.0.1"
    ):
        raise SystemExit("Use dedicated disposable local audit services")
    return owner_url


async def main():
    owner_url = require_local_services()
    role = "audit_closure_" + uuid4().hex
    role_password = token_hex(24)
    os.environ["POSTGRES_URL"] = owner_url.set(username=role, password=role_password).render_as_string(hide_password=False)
    os.environ["ENVIRONMENT"] = "production"
    os.environ["DEV_SKIP_AUTH"] = "false"

    from backend.core.config import settings
    from backend.core.security import hash_password
    from backend.database.engine import AsyncSessionLocal, Base, engine
    from backend.database.redis_client import get_redis
    from backend.database.tenant import bind_tenant_context
    from backend.main import app
    from backend.models.device import Device
    from backend.models.game_account import AccountStatus, GameAccount
    from backend.models.organization import Organization
    from backend.models.pipeline_settings import PipelineSettings
    from backend.models.script import Script, ScriptVersion
    from backend.models.task import Task, TaskStatus
    from backend.models.user import User
    from backend.services.orchestrator.orchestration_engine import OrchestrationEngine

    assert settings.ENVIRONMENT == "production"
    owner = create_async_engine(owner_url)
    owner_sessions = async_sessionmaker(owner, expire_on_commit=False)
    tables = ", ".join(f'public."{table}"' for table in sorted(Base.metadata.tables))
    functions = ", ".join((
        "sphere_auth.api_key_org(text)", "sphere_auth.device_refresh_org(text)",
        "sphere_auth.user_login_org(text)", "sphere_auth.user_refresh_org(text)",
        "sphere_auth.due_batch_admissions()", "sphere_auth.pipeline_work(text)",
        "sphere_auth.schedule_work(uuid)", "sphere_auth.task_dispatch_work(text,uuid)",
        "sphere_auth.watchdog_work(integer,integer,uuid)",
    ))
    async with owner.begin() as db:
        await db.execute(text(f'''CREATE ROLE "{role}" LOGIN NOSUPERUSER NOBYPASSRLS
            NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD '{role_password}' '''))
        await db.execute(text(f'GRANT USAGE ON SCHEMA public, sphere_auth TO "{role}"'))
        await db.execute(text(f'GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO "{role}"'))
        await db.execute(text(f'GRANT EXECUTE ON FUNCTION {functions} TO "{role}"'))

    password = token_hex(24)
    suffix = uuid4().hex
    async with owner_sessions() as db:
        org_a = Organization(name="Closure A", slug=f"closure-a-{suffix}")
        org_b = Organization(name="Closure B", slug=f"closure-b-{suffix}")
        db.add_all([org_a, org_b])
        await db.flush()
        user = User(org_id=org_a.id, email=f"{suffix}@example.org", role="org_owner", password_hash=hash_password(password))
        device_a = Device(org_id=org_a.id, name="Closure own device")
        device_b = Device(org_id=org_b.id, name="Closure second organization device")
        script = Script(org_id=org_a.id, name="Closure script")
        account = GameAccount(
            org_id=org_a.id, game="fixture", login=suffix, password_encrypted="",
            status=AccountStatus.cooldown, cooldown_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        config = PipelineSettings(org_id=org_a.id, orchestration_enabled=True)
        db.add_all([user, device_a, device_b, script, account, config])
        await db.flush()
        version = ScriptVersion(org_id=org_a.id, script_id=script.id, dag={"nodes": []})
        db.add(version)
        await db.flush()
        script.current_version_id = version.id
        task = Task(
            org_id=org_a.id, device_id=device_a.id, script_id=script.id, script_version_id=version.id,
            status=TaskStatus.COMPLETED,
        )
        db.add(task)
        await db.commit()

    report = {}
    try:
        async with app.router.lifespan_context(app):
            async with engine.connect() as db:
                db_role = (await db.execute(text("""SELECT current_user, rolsuper, rolbypassrls,
                    row_security_active('devices'), row_security_active('pipeline_settings')
                    FROM pg_roles WHERE rolname=current_user"""))).one()
            report["runtime"] = {
                "environment": settings.ENVIRONMENT, "lifespan_startup_completed": True,
                "connected_as_created_role": db_role[0] == role, "superuser": db_role[1],
                "bypass_rls": db_role[2], "devices_rls_active": db_role[3],
                "pipeline_settings_rls_active": db_role[4], "mapped_tables_granted": len(Base.metadata.tables),
                "redis_ping": await (await get_redis()).ping(),
            }
            assert report["runtime"]["connected_as_created_role"] and db_role[3] and db_role[4]
            assert not db_role[1] and not db_role[2]
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://audit.local") as client:
                statuses = {}
                for endpoint in ("health/healthz", "health/readyz"):
                    response = await client.get(f"/api/v1/{endpoint}")
                    assert response.status_code == 200, endpoint
                    statuses[endpoint] = response.status_code
                login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": password})
                assert login.status_code == 200, login.status_code
                headers = {"Authorization": "Bearer " + login.json()["access_token"]}
                me = await client.get("/api/v1/auth/me", headers=headers)
                devices = await client.get("/api/v1/devices", headers=headers)
                jobs = await client.get("/api/v1/tasks", headers=headers)
                accounts = await client.get("/api/v1/game-accounts", headers=headers)
                config_view = await client.get("/api/v1/pipeline-settings", headers=headers)
                refreshed = await client.post("/api/v1/auth/refresh")
                assert all(response.status_code == 200 for response in (me, devices, jobs, accounts, config_view, refreshed))
                assert me.json()["id"] == str(user.id)
                assert {item["id"] for item in devices.json()["items"]} == {str(device_a.id)}
                assert {item["id"] for item in jobs.json()["items"]} == {str(task.id)}
                assert {item["id"] for item in accounts.json()["items"]} == {str(account.id)}
                assert config_view.json()["orchestration_enabled"] is True
                statuses.update({"auth/login": login.status_code, "auth/me": me.status_code,
                                 "devices": devices.status_code, "tasks": jobs.status_code,
                                 "game-accounts": accounts.status_code, "pipeline-settings": config_view.status_code,
                                 "auth/refresh": refreshed.status_code})
                report["http"] = {"status_codes": statuses, "own_identity_matches": True,
                                  "inventory_contains_only_own_device": True,
                                  "tasks_and_accounts_contain_own_fixture": True,
                                  "orchestration_enabled_readback": True}

            worker = OrchestrationEngine()
            async with AsyncSessionLocal() as db:
                unscoped_count = await db.scalar(select(func.count()).select_from(PipelineSettings))
            await worker._tick()
            async with owner_sessions() as db:
                before = (await db.get(GameAccount, account.id)).status.value

            @asynccontextmanager
            async def scoped_runtime_session():
                async with AsyncSessionLocal() as db:
                    await bind_tenant_context(db, str(org_a.id))
                    yield db

            with patch("backend.services.orchestrator.orchestration_engine.AsyncSessionLocal", scoped_runtime_session):
                await worker._tick()
            async with owner_sessions() as db:
                after = (await db.get(GameAccount, account.id)).status.value
            report["orchestration_cooldown_control"] = {
                "unscoped_settings_visible": unscoped_count,
                "status_after_real_worker_tick": before,
                "status_after_same_runtime_role_with_tenant_bound": after,
            }
        report["runtime"]["lifespan_shutdown_completed"] = True
    finally:
        await engine.dispose()
        await owner.dispose()

    payload = json.dumps(report, indent=2) + "\n"
    Path(__file__).with_name("backend-closure-observations.json").write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    asyncio.run(main())
