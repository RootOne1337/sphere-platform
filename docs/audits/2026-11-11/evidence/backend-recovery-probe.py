"""Local PostgreSQL audit fixtures with in-process transport recorders."""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


def require_audit_database():
    url = make_url(os.environ["POSTGRES_URL"])
    if (
        os.environ.get("SPHERE_RUN_INTEGRATION") != "1"
        or url.host != "127.0.0.1"
        or url.database != "sphere_audit_20261111"
    ):
        raise SystemExit("Use only the dedicated disposable PostgreSQL audit database")


async def main():
    import backend.models  # noqa: F401  Registers all ORM relationships.
    from backend.database.engine import AsyncSessionLocal, engine
    from backend.models.device import Device
    from backend.models.organization import Organization
    from backend.models.pipeline import Pipeline, PipelineRun
    from backend.models.schedule import Schedule, ScheduleExecution, ScheduleTargetType
    from backend.models.script import Script, ScriptVersion
    from backend.models.task import Task, TaskStatus
    from backend.models.task_batch import TaskBatch, TaskBatchStatus
    from backend.services.batch_admission import advance_batch, initialize_plan
    from backend.services.orchestrator.pipeline_service import PipelineService
    from backend.services.scheduler.scheduler_engine import SchedulerEngine
    from backend.services.task_service import TaskService
    from backend.tasks.task_heartbeat_watchdog import _process_stale_tasks

    report = {}
    suffix = uuid4().hex
    past = datetime.now(timezone.utc) - timedelta(minutes=65)
    async with AsyncSessionLocal() as db:
        org = Organization(name="Recovery audit", slug=f"recovery-audit-{suffix}")
        db.add(org)
        await db.flush()
        devices = [Device(org_id=org.id, name=f"Fixture {index}") for index in range(4)]
        script = Script(org_id=org.id, name="Audit script")
        pipeline = Pipeline(org_id=org.id, name="Inactive audit pipeline", is_active=False, steps=[])
        db.add_all([*devices, script, pipeline])
        await db.flush()
        version = ScriptVersion(org_id=org.id, script_id=script.id, dag={"nodes": []})
        path_version = ScriptVersion(org_id=org.id, script_id=script.id, version=2, dag={
            "entry_node": "fixture",
            "nodes": [{"id": "fixture", "action": {"type": "pointer_path", "path": {
                "schema_version": 1, "frame_width": 10, "frame_height": 10,
                "points": [{"t_ms": 0, "action": 0, "x": 1, "y": 1}, {"t_ms": 2, "action": 1, "x": 1, "y": 1}],
            }}}],
        })
        db.add_all([version, path_version])
        await db.flush()
        script.current_version_id = path_version.id
        batch = TaskBatch(id=uuid4(), org_id=org.id, script_id=script.id, total=1, wave_config={})
        initialize_plan(batch, [[devices[0].id]], path_version.id)
        expiry_tasks = [
            Task(org_id=org.id, device_id=device.id, script_id=script.id,
                 script_version_id=version.id, status=TaskStatus.QUEUED, created_at=past)
            for device in devices[1:3]
        ]
        callback_task = Task(
            org_id=org.id, device_id=devices[3].id, script_id=script.id, script_version_id=version.id,
            status=TaskStatus.RUNNING, input_params={"webhook_url": "https://receiver.example.test/fixture"},
        )
        schedule = Schedule(
            org_id=org.id, name="Inactive pipeline schedule", target_type=ScheduleTargetType.PIPELINE,
            pipeline_id=pipeline.id, interval_seconds=3600, only_online=False, device_ids=[str(devices[3].id)],
            next_fire_at=past,
        )
        db.add_all([batch, *expiry_tasks, callback_task, schedule])
        await db.commit()

    async def dispatch(device, agent_version):
        sender = AsyncMock(return_value=True)
        publisher = SimpleNamespace(send_command_live=sender)
        status = {str(device.id): SimpleNamespace(status="online", agent_version_code=agent_version)}
        cache = SimpleNamespace(bulk_get_status=AsyncMock(return_value=status))
        async with AsyncSessionLocal() as db:
            await TaskService(db, status_cache=cache, publisher=publisher).dispatch_pending_tasks(
                org_id=org.id, device_id=device.id, include_cancellations=False,
            )
        return [call.args[1] for call in sender.await_args_list]

    async def watch(task):
        async with AsyncSessionLocal() as db:
            stops, expired = await _process_stale_tasks(
                db, stale_buffer_seconds=300, queued_stale_minutes=60, org_id=org.id, task_id=task.id,
            )
            await db.commit()
        return {"stop_requests": len(stops), "local_expirations": len(expired)}

    assert await advance_batch(AsyncSessionLocal, batch.id, org.id)
    rejected_commands = await dispatch(devices[0], 10280)
    retry_commands = await dispatch(devices[0], 10280)
    async with AsyncSessionLocal() as db:
        task = await db.scalar(select(Task).where(Task.batch_id == batch.id))
        stored = await db.get(TaskBatch, batch.id)
        assert task.status == TaskStatus.FAILED and stored.status in (TaskBatchStatus.PENDING, TaskBatchStatus.RUNNING)
        report["dispatch_rejection_batch_accounting"] = {
            "task_status": task.status.value, "task_error": task.error_message,
            "batch_status": stored.status.value, "batch_failed": stored.failed,
            "batch_total": stored.total, "admission_state": stored.admission_state,
            "admission_outcome": stored.admission_receipts[0]["outcome"],
            "publishes": len(rejected_commands) + len(retry_commands),
        }

    overdue, control = expiry_tasks
    sent = await dispatch(devices[1], 10281)
    watched = await watch(overdue)
    control_watched = await watch(control)
    control_sent = await dispatch(devices[2], 10281)
    async with AsyncSessionLocal() as db:
        first = await db.get(Task, overdue.id)
        second = await db.get(Task, control.id)
        report["overdue_queue_dispatch_order"] = {
            "simulated_queue_age_minutes": 65, "queue_deadline_minutes": 60,
            "dispatch_first": {
                "publish_count": len(sent), "command_type": sent[0]["type"] if sent else None,
                "command_ttl_seconds": sent[0]["ttl_seconds"] if sent else None,
                "persisted_status": first.status.value, "cancel_pending": first.cancel_requested_at is not None,
                **watched,
            },
            "watchdog_first_control": {
                "publish_count": len(control_sent), "persisted_status": second.status.value,
                "cancel_pending": second.cancel_requested_at is not None, **control_watched,
            },
        }

    outbound = []
    delivered = asyncio.Event()
    client_type = httpx.AsyncClient

    async def receiver(request):
        async with AsyncSessionLocal() as db:
            current = await db.get(Task, callback_task.id)
            status_visible_at_delivery = current.status.value
        body = json.loads(request.content)
        outbound.append({"event_type": body["event_type"], "db_status_at_delivery": status_visible_at_delivery})
        delivered.set()
        return httpx.Response(204)

    queue = SimpleNamespace(mark_completed=AsyncMock())
    with patch("backend.services.webhook_service.httpx.AsyncClient", side_effect=lambda **kwargs: client_type(
        transport=httpx.MockTransport(receiver), **kwargs,
    )):
        for abort in (True, False):
            delivered.clear()
            async with AsyncSessionLocal() as db:
                accepted = await TaskService(db, queue=queue).handle_task_result(
                    str(callback_task.id), str(devices[3].id), {"success": True}, org_id=str(org.id),
                )
                assert accepted
                await asyncio.wait_for(delivered.wait(), 3)
                if abort:
                    try:
                        await db.execute(text("SELECT 1 / 0"))
                    except DBAPIError:
                        await db.rollback()
                else:
                    await db.commit()
            async with AsyncSessionLocal() as db:
                result = await db.get(Task, callback_task.id)
                outbound[-1]["db_status_after_transaction"] = result.status.value
    report["callback_before_commit"] = {"requests": outbound}

    async with AsyncSessionLocal() as db:
        try:
            await PipelineService(db).run(pipeline.id, devices[3].id, org.id)
        except HTTPException as error:
            manual_status = error.status_code
        else:
            manual_status = None
    await SchedulerEngine()._fire_schedule(schedule.id, org.id)
    async with AsyncSessionLocal() as db:
        receipt = await db.scalar(select(ScheduleExecution).where(ScheduleExecution.schedule_id == schedule.id))
        runs = (await db.scalars(select(PipelineRun).where(PipelineRun.pipeline_id == pipeline.id))).all()
        report["inactive_pipeline_schedule"] = {
            "pipeline_active": pipeline.is_active, "manual_http_exception": manual_status,
            "schedule_receipt": receipt.status.value if receipt else None,
            "run_statuses": [run.status.value for run in runs],
        }
    await engine.dispose()
    evidence = json.dumps(report, indent=2) + "\n"
    Path(__file__).with_name("backend-recovery-observations.json").write_text(evidence, encoding="utf-8")
    print(evidence)


if __name__ == "__main__":
    require_audit_database()
    asyncio.run(main())
