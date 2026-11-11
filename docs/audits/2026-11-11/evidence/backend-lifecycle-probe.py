"""Functional lifecycle checks in dedicated local PostgreSQL and Redis."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url


def require_local_services():
    db = make_url(os.environ["POSTGRES_URL"])
    redis = urlparse(os.environ["REDIS_URL"])
    if (
        os.environ.get("SPHERE_RUN_INTEGRATION") != "1"
        or db.database != "sphere_audit_20261111"
        or db.host != "127.0.0.1"
        or redis.hostname != "127.0.0.1"
    ):
        raise SystemExit("Use dedicated disposable local audit services")
    os.environ["DEV_SKIP_AUTH"] = "false"


async def main():
    from backend.api.ws.android.router import handle_task_progress
    from backend.core.security import create_access_token
    from backend.database.engine import AsyncSessionLocal, engine
    from backend.database.redis_client import connect_redis, disconnect_redis, get_redis
    from backend.main import app
    from backend.models.device import Device
    from backend.models.game_account import GameAccount
    from backend.models.organization import Organization
    from backend.models.pipeline import Pipeline
    from backend.models.script import Script, ScriptVersion
    from backend.models.task import Task, TaskStatus
    from backend.models.user import User
    from backend.schemas.game_accounts import AssignAccountRequest
    from backend.services.game_account_service import GameAccountService

    run = uuid4().hex
    output = {}
    async with AsyncSessionLocal() as db:
        org = Organization(name="Lifecycle fixture", slug=f"lifecycle-fixture-{run}")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email=f"{run}@example.test", role="org_owner", password_hash="fixture")
        devices = [Device(org_id=org.id, name=f"Lifecycle device {i}") for i in range(3)]
        accounts = [
            GameAccount(org_id=org.id, game="fixture", login=f"{run}-{i}", password_encrypted="")
            for i in range(2)
        ]
        script = Script(org_id=org.id, name="Lifecycle script")
        pipeline = Pipeline(org_id=org.id, name="Lifecycle pipeline", is_active=True, steps=[])
        db.add_all([user, *devices, *accounts, script, pipeline])
        await db.flush()
        version = ScriptVersion(org_id=org.id, script_id=script.id, dag={"nodes": []})
        db.add(version)
        await db.flush()
        script.current_version_id = version.id
        task = Task(
            org_id=org.id, device_id=devices[0].id, script_id=script.id, script_version_id=version.id,
            status=TaskStatus.RUNNING,
        )
        db.add(task)
        await db.commit()

    token, _ = create_access_token(subject=str(user.id), org_id=str(org.id), role=user.role)
    await connect_redis()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://audit.local", headers={"Authorization": f"Bearer {token}"},
        ) as client:
            account_path = f"/api/v1/game-accounts/{accounts[0].id}"
            async with AsyncSessionLocal() as first_db:
                first = await GameAccountService(first_db).assign_account(
                    accounts[0].id, org.id, AssignAccountRequest(device_id=devices[0].id),
                )
                second = asyncio.create_task(client.post(f"{account_path}/assign", json={"device_id": str(devices[1].id)}))
                try:
                    async with engine.connect() as observer:
                        async with asyncio.timeout(3):
                            while True:
                                waiting = await observer.scalar(text("""
                                    SELECT count(*) FROM pg_stat_activity
                                    WHERE datname = current_database() AND wait_event_type = 'Lock'
                                      AND query LIKE 'UPDATE game_accounts%'
                                """))
                                await observer.rollback()
                                if waiting:
                                    break
                                await asyncio.sleep(0.02)
                    await first_db.commit()
                    second_result = await asyncio.wait_for(second, 3)
                finally:
                    if not second.done():
                        second.cancel()
                        await asyncio.gather(second, return_exceptions=True)
            readback = await client.get(account_path)
            control = await client.post(f"{account_path}/assign", json={"device_id": str(devices[0].id)})
            output["concurrent_account_assignment"] = {
                "first_service_selected_device": first.device_id == devices[0].id,
                "second_waiting_on_update_lock_before_first_commit": bool(waiting),
                "second_http": second_result.status_code,
                "second_response_selected_its_device": second_result.json().get("device_id") == str(devices[1].id),
                "committed_readback_selected_second_device": readback.json().get("device_id") == str(devices[1].id),
                "serial_conflict_control_http": control.status_code,
            }

            retired = devices[2]
            retired_response = await client.delete(f"/api/v1/devices/{retired.id}")
            inventory = await client.get("/api/v1/devices")
            active_ids = {item["id"] for item in inventory.json()["items"]}
            task_admission = await client.post("/api/v1/tasks", json={"device_id": str(retired.id), "script_id": str(script.id)})
            account_admission = await client.post(
                f"/api/v1/game-accounts/{accounts[1].id}/assign", json={"device_id": str(retired.id)},
            )
            pipeline_admission = await client.post(f"/api/v1/pipelines/{pipeline.id}/run", json={"device_id": str(retired.id)})
            async with AsyncSessionLocal() as db:
                device = await db.get(Device, retired.id)
                account = await db.get(GameAccount, accounts[1].id)
                output["retired_device_admission"] = {
                    "retirement_http": retired_response.status_code,
                    "device_active_readback": device.is_active,
                    "retired_present_in_active_inventory": str(retired.id) in active_ids,
                    "task_admission_http": task_admission.status_code,
                    "account_assign_http": account_admission.status_code,
                    "account_status_readback": account.status.value,
                    "account_assigned_to_retired_device": account.device_id == retired.id,
                    "pipeline_run_http": pipeline_admission.status_code,
                    "pipeline_run_status": pipeline_admission.json().get("status"),
                }

            path = f"/api/v1/tasks/{task.id}"
            await handle_task_progress(str(devices[0].id), str(org.id), {
                "task_id": str(task.id), "nodes_done": 7, "total_nodes": 10, "current_node": "fixture",
            })
            before = await client.get(f"{path}/progress")
            logs_before = await client.get(f"{path}/live-logs")
            redis = await get_redis()
            progress_key = f"task_progress:{task.id}"
            log_key = f"task_progress_log:{task.id}"
            existing_ttl = await redis.ttl(progress_key)
            await redis.expire(progress_key, 0)
            await redis.expire(log_key, 0)
            after = await client.get(f"{path}/progress")
            logs_after = await client.get(f"{path}/live-logs")
            detail = await client.get(path)
            output["expired_progress_readback"] = {
                "progress_before_http": before.status_code, "progress_before": before.json()["progress"],
                "normal_progress_ttl_seconds": existing_ttl,
                "progress_after_http": after.status_code, "progress_after": after.json(),
                "logs_before_count": len(logs_before.json()), "logs_after_count": len(logs_after.json()),
                "logs_after_http": logs_after.status_code, "sql_task_status_after": detail.json()["status"],
            }
    finally:
        await disconnect_redis()
        await engine.dispose()

    evidence = json.dumps(output, indent=2) + "\n"
    Path(__file__).with_name("backend-lifecycle-observations.json").write_text(evidence, encoding="utf-8")
    print(evidence)


if __name__ == "__main__":
    require_local_services()
    asyncio.run(main())
