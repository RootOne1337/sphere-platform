"""Exercise event state and group deletion in an isolated SQLite fixture."""
import asyncio
import json
from types import SimpleNamespace

from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import tests.conftest  # noqa: F401 - SQLite model adapters and relationship fixtures
from backend.api.v1.device_events.router import create_device_event, mark_event_processed
from backend.api.v1.groups.router import delete_group
from backend.database.engine import Base
from backend.models.device import Device
from backend.models.device_event import DeviceEvent
from backend.models.device_group import DeviceGroup
from backend.models.event_trigger import EventTrigger
from backend.models.organization import Organization
from backend.models.pipeline import Pipeline, PipelineRun
from backend.models.schedule import Schedule
from backend.schemas.device_events import CreateDeviceEventRequest
from backend.services.device_event_service import DeviceEventService
from backend.services.event_reactor import EventReactor
from backend.services.group_service import GroupService


async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_constraints(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as db:
            org = Organization(name="Closure fixture", slug="closure-fixture")
            db.add(org)
            await db.flush()
            device = Device(org_id=org.id, name="Fixture", serial="closure-device")
            group = DeviceGroup(org_id=org.id, name="Schedule target")
            empty_group = DeviceGroup(org_id=org.id, name="No dependencies")
            pipeline = Pipeline(org_id=org.id, name="Paused fixture", is_active=False)
            db.add_all([device, group, empty_group, pipeline])
            await db.flush()
            trigger = EventTrigger(org_id=org.id, name="Fixture match", event_type_pattern="fixture.*",
                                   pipeline_id=pipeline.id, cooldown_seconds=0, is_active=True)
            schedule = Schedule(org_id=org.id, name="Group consumer", interval_seconds=3600,
                                target_type="pipeline", pipeline_id=pipeline.id, group_id=group.id)
            db.add_all([trigger, schedule])
            await db.commit()

            actor = SimpleNamespace(org_id=org.id)
            group_id, control_id, schedule_id = group.id, empty_group.id, schedule.id
            created = await create_device_event(
                CreateDeviceEventRequest(device_id=device.id, event_type="fixture.notice"),
                actor, DeviceEventService(db), db,
            )
            receipt = await mark_event_processed(created.id, actor, DeviceEventService(db), db)
            marked = await db.get(DeviceEvent, created.id)
            automatic = await EventReactor(db).process_event(org.id, device.id, "fixture.notice")
            await db.commit()
            run_count = await db.scalar(select(func.count()).select_from(PipelineRun))
            assert not created.processed and receipt.status_code == 204 and marked.processed
            assert automatic.processed and run_count == 0 and trigger.total_triggers == 0

            try:
                await delete_group(group_id, actor, GroupService(db), db)
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("Group deletion should hit the schedule foreign key")
            kept_group = await db.get(DeviceGroup, group_id) is not None
            kept_schedule = await db.get(Schedule, schedule_id) is not None
            await delete_group(control_id, actor, GroupService(db), db)
            deleted_control = await db.get(DeviceGroup, control_id) is None
            assert kept_group and kept_schedule and deleted_control
            print(json.dumps({
                "events": {"http_created_processed": created.processed, "manual_mark_http": receipt.status_code,
                           "manually_marked": True, "reactor_processed": True, "pipeline_runs": run_count},
                "group_delete": {"foreign_key_rejection": True, "group_survived": kept_group,
                                 "schedule_survived": kept_schedule, "unreferenced_group_deleted": deleted_control},
            }))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
