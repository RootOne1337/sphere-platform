"""Non-owner scheduler visibility only; no tasks, devices or pilot operations."""

from datetime import datetime, timedelta, timezone

from backend.models.schedule import Schedule, ScheduleTargetType
from backend.services.scheduler.scheduler_engine import SchedulerEngine


async def test_due_exhausted_schedule_is_retired_by_runtime_worker(runtime_db, monkeypatch):
    r = runtime_db
    async with r.world.sessions() as db:
        schedule = Schedule(org_id=r.world.org_a.id, name="isolated-runtime-visibility",
            interval_seconds=60, target_type=ScheduleTargetType.SCRIPT, script_id=r.world.script.id,
            max_runs=1, total_runs=1, is_active=True,
            next_fire_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        db.add(schedule)
        await db.commit()
    monkeypatch.setattr("backend.services.scheduler.scheduler_engine.AsyncSessionLocal", r.sessions)
    await SchedulerEngine()._tick()
    async with r.world.sessions() as db:
        row = await db.get(Schedule, schedule.id)
        assert row.is_active is False, "RLS startup cannot find even due exhausted schedules"
