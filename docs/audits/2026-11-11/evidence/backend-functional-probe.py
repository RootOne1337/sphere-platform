"""Functional observations on disposable local PostgreSQL and Redis only."""

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import MissingGreenlet, MultipleResultsFound


def require_audit_environment():
    db = make_url(os.environ["POSTGRES_URL"])
    redis = urlparse(os.environ["REDIS_URL"])
    if (
        os.environ.get("SPHERE_RUN_INTEGRATION") != "1"
        or db.database != "sphere_audit_20261111"
        or db.host != "127.0.0.1"
        or redis.hostname != "127.0.0.1"
    ):
        raise SystemExit("This probe needs the dedicated disposable audit database and Redis")
    os.environ["DEV_SKIP_AUTH"] = "false"


async def run():
    from backend.core.security import create_access_token
    from backend.database.engine import AsyncSessionLocal, engine
    from backend.database.redis_client import connect_redis, disconnect_redis, get_redis
    from backend.main import app
    from backend.models.account_session import AccountSession
    from backend.models.device import Device
    from backend.models.event_trigger import EventTrigger
    from backend.models.game_account import GameAccount
    from backend.models.organization import Organization
    from backend.models.pipeline import Pipeline, PipelineBatch, PipelineRun
    from backend.models.schedule import ScheduleExecution
    from backend.models.script import Script
    from backend.models.user import User
    from backend.schemas.account_sessions import EndSessionRequest
    from backend.services.account_session_service import AccountSessionService
    from backend.services.event_reactor import EventReactor
    from backend.services.scheduler.scheduler_engine import SchedulerEngine

    sample = uuid4().hex
    results = {}
    async with AsyncSessionLocal() as db:
        org = Organization(name="Audit fixture", slug=f"audit-functional-{sample}")
        db.add(org)
        await db.flush()
        user = User(org_id=org.id, email=f"{sample}@example.test", role="org_owner", password_hash="fixture")
        device = Device(org_id=org.id, name="Audit fixture device", meta={"workstation_id": str(uuid4())})
        device_two = Device(org_id=org.id, name="Audit fixture device two")
        game = GameAccount(org_id=org.id, game="fixture", login=sample, password_encrypted="")
        script = Script(org_id=org.id, name="Audit fixture script")
        pipeline = Pipeline(org_id=org.id, name="Audit fixture pipeline", steps=[], is_active=True)
        db.add_all([user, device, device_two, game, script, pipeline])
        await db.flush()
        trigger = EventTrigger(
            org_id=org.id, name="Hour limit fixture", event_type_pattern="audit.fixture",
            pipeline_id=pipeline.id, cooldown_seconds=0, max_triggers_per_hour=1,
        )
        existing = AccountSession(
            org_id=org.id, account_id=game.id, device_id=device.id,
            started_at=func.now(), nodes_executed=17, errors_count=3, level_after=8, balance_after=145,
        )
        db.add_all([trigger, existing])
        await db.commit()

    token, _ = create_access_token(subject=str(user.id), org_id=str(org.id), role=user.role)
    await connect_redis()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://audit.local", headers={"Authorization": f"Bearer {token}"},
        ) as client:
            body = {"account_id": str(game.id), "device_id": str(device.id)}
            previous = await client.get(f"/api/v1/account-sessions/{existing.id}")
            started = await client.post("/api/v1/account-sessions", json=body)
            after_start = await client.get("/api/v1/account-sessions", params={"active_only": True})
            results["start_session"] = {
                "existing_get_http": previous.status_code, "start_http": started.status_code,
                "active_count_after_start": after_start.json()["total"],
            }

            ended = await client.post(f"/api/v1/account-sessions/{existing.id}/end", json={"end_reason": "manual"})
            persisted = await client.get(f"/api/v1/account-sessions/{existing.id}")
            fields = ("nodes_executed", "errors_count", "level_after", "balance_after")
            results["partial_session_end"] = {
                "end_http": ended.status_code, "readback_http": persisted.status_code,
                "before": {field: previous.json()[field] for field in fields},
                "persisted_after": {field: persisted.json()[field] for field in fields},
                "ended_at_after_http": persisted.json()["ended_at"],
            }
            async with AsyncSessionLocal() as db:
                try:
                    await AccountSessionService(db).end_session(
                        existing.id, org.id, EndSessionRequest(end_reason="manual"),
                    )
                except MissingGreenlet:
                    results["partial_session_end"]["service_response_error"] = "MissingGreenlet"
                record = await db.get(AccountSession, existing.id)
                results["partial_session_end"]["flushed_before_rollback"] = {
                    field: getattr(record, field) for field in fields
                }
                await db.rollback()

            schedule_input = {
                "name": "Audit fixture schedule", "interval_seconds": 3600,
                "target_type": "script", "script_id": str(script.id), "device_ids": [str(device.id)],
            }
            created = await client.post("/api/v1/schedules", json=schedule_input)
            assert created.status_code == 201, created.text
            schedule_id = created.json()["id"]
            toggled = await client.post(f"/api/v1/schedules/{schedule_id}/toggle", params={"active": False})
            disabled = await client.post(f"/api/v1/schedules/{schedule_id}/fire-now")
            disabled_readback = await client.get(f"/api/v1/schedules/{schedule_id}")
            disabled_seen = (UUID(schedule_id), org.id) in await SchedulerEngine()._discover_schedules()
            toggled_on = await client.post(f"/api/v1/schedules/{schedule_id}/toggle", params={"active": True})
            enabled = await client.post(f"/api/v1/schedules/{schedule_id}/fire-now")
            enabled_seen = (UUID(schedule_id), org.id) in await SchedulerEngine()._discover_schedules()
            results["schedule_fire_now"] = {
                "create_http": created.status_code, "disable_http": toggled.status_code,
                "disabled_fire_http": disabled.status_code,
                "disabled_next_fire_set": bool(disabled_readback.json()["next_fire_at"]),
                "disabled_readback_active": disabled_readback.json()["is_active"],
                "disabled_discovered": disabled_seen, "enable_http": toggled_on.status_code,
                "enabled_fire_http": enabled.status_code,
                "enabled_discovered": enabled_seen,
            }

            cron_input = {**schedule_input, "interval_seconds": None, "cron_expression": "invalid cron"}
            invalid_cron = await client.post("/api/v1/schedules", json=cron_input)
            two_triggers = await client.patch(
                f"/api/v1/schedules/{schedule_id}", json={"cron_expression": "0 * * * *", "interval_seconds": 120}
            )
            schedule_readback = await client.get(f"/api/v1/schedules/{schedule_id}")
            results["schedule_validation"] = {
                "invalid_cron_http": invalid_cron.status_code, "two_triggers_patch_http": two_triggers.status_code,
                "persisted_cron": schedule_readback.json()["cron_expression"],
                "persisted_interval_seconds": schedule_readback.json()["interval_seconds"],
            }

            settings_on = await client.patch("/api/v1/pipeline-settings", json={
                "scheduler_enabled": True, "registration_script_id": str(script.id),
            })
            settings_off = await client.post("/api/v1/pipeline-settings/toggle/scheduler", json={"enabled": False})
            cleared = await client.patch("/api/v1/pipeline-settings", json={"registration_script_id": None})
            settings_readback = await client.get("/api/v1/pipeline-settings")
            results["settings_clear_script"] = {
                "set_http": settings_on.status_code, "clear_http": cleared.status_code,
                "registration_script_retained": settings_readback.json()["registration_script_id"] == str(script.id),
            }

            controlled_schedule = await client.post("/api/v1/schedules", json={
                **schedule_input, "target_type": "pipeline", "script_id": None,
                "pipeline_id": str(pipeline.id), "only_online": False,
            })
            controlled_id = UUID(controlled_schedule.json()["id"])
            await client.post(f"/api/v1/schedules/{controlled_id}/fire-now")
            scheduler = SchedulerEngine()
            await scheduler._fire_schedule(controlled_id, org.id)
            async with AsyncSessionLocal() as db:
                receipt = await db.scalar(select(ScheduleExecution).where(ScheduleExecution.schedule_id == controlled_id))
                results["scheduler_master_toggle"] = {
                    "toggle_http": settings_off.status_code,
                    "scheduler_enabled_readback": settings_readback.json()["scheduler_enabled"],
                    "execution_status": receipt.status.value if receipt else None,
                    "devices_targeted": receipt.devices_targeted if receipt else None,
                }

            connect = await client.post(f"/api/v1/devices/{device.id}/connect")
            screenshot = await client.get(f"/api/v1/devices/{device.id}/screenshot")
            redis = await get_redis()
            results["legacy_device_commands"] = {
                "connect_http": connect.status_code, "screenshot_http": screenshot.status_code,
                "screenshot_state": screenshot.json()["status"],
                "connect_redis_ttl_in_range": 0 < await redis.ttl(f"cmd:adb_connect:{device.id}") <= 30,
                "screenshot_redis_ttl_in_range": 0 < await redis.ttl(f"cmd:screenshot:{device.id}") <= 30,
            }

            trigger_patched = await client.patch(
                f"/api/v1/event-triggers/{trigger.id}", json={"description": "Audit description"}
            )
            trigger_readback = await client.get(f"/api/v1/event-triggers/{trigger.id}")
            results["event_trigger_patch"] = {
                "patch_http": trigger_patched.status_code, "readback_http": trigger_readback.status_code,
                "description_persisted": trigger_readback.json()["description"] == "Audit description",
            }

            for _ in range(2):
                async with AsyncSessionLocal() as db:
                    await EventReactor(db).process_event(org.id, device.id, "audit.fixture")
                    await db.commit()
            async with AsyncSessionLocal() as db:
                current = await db.get(EventTrigger, trigger.id)
                runs = await db.scalar(select(func.count()).select_from(PipelineRun).where(
                    PipelineRun.pipeline_id == pipeline.id, PipelineRun.context == {},
                ))
                results["event_trigger_hour_limit"] = {
                    "configured_limit": current.max_triggers_per_hour, "trigger_count": current.total_triggers,
                    "persisted_pipeline_runs": runs,
                }

                svc = AccountSessionService(db)
                await svc.start_session_internal(org.id, game.id, device.id)
                await svc.start_session_internal(org.id, game.id, device.id)
                await db.commit()

            pipeline_batch = await client.post(f"/api/v1/pipelines/{pipeline.id}/run-batch", json={
                "device_ids": [str(device.id), str(device_two.id)],
                "wave_size": 1, "wave_delay_seconds": 3600,
            })
            async with AsyncSessionLocal() as db:
                batch = await db.scalar(select(PipelineBatch).where(
                    PipelineBatch.pipeline_id == pipeline.id, PipelineBatch.wave_config["wave_size"].astext == "1",
                ))
                batch_runs = (await db.scalars(select(PipelineRun).where(
                    PipelineRun.pipeline_id == pipeline.id,
                    PipelineRun.context["batch_id"].astext == str(batch.id),
                ))).all()
                results["pipeline_batch_waves"] = {
                    "batch_http": pipeline_batch.status_code, "persisted_wave_config": batch.wave_config,
                    "first_read_run_statuses": sorted(run.status.value for run in batch_runs),
                }

            async with AsyncSessionLocal() as db:
                active = await db.scalar(select(func.count()).select_from(AccountSession).where(
                    AccountSession.account_id == game.id, AccountSession.ended_at.is_(None),
                ))
                try:
                    await EventReactor(db)._end_active_session(game.id, org.id, "error")
                except MultipleResultsFound:
                    outcome = "MultipleResultsFound"
                else:
                    outcome = "ok"
                results["duplicate_active_sessions"] = {"persisted_count": active, "event_reactor_end": outcome}
    finally:
        await disconnect_redis()
        await engine.dispose()

    # Deliberately exclude app logs containing ephemeral ids and SQL parameters.
    Path(__file__).with_name("backend-functional-observations.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    require_audit_environment()
    asyncio.run(run())
