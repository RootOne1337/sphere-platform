"""Regression coverage for the schedule wall-clock and backlog policy."""

from datetime import datetime, timezone

import pytest

from backend.models.schedule import Schedule
from backend.services.scheduler.schedule_timing import next_cron_slot, next_schedule_slot


@pytest.mark.parametrize(("expression", "zone", "after", "expected"), [
    ("30 2 * * *", "America/New_York", "2026-03-08T06:59:59+00:00", "2026-03-09T06:30:00+00:00"),
    ("30 1 * * *", "America/New_York", "2026-11-01T05:00:00+00:00", "2026-11-01T05:30:00+00:00"),
    ("30 1 * * *", "America/New_York", "2026-11-01T05:30:00+00:00", "2026-11-02T06:30:00+00:00"),
    ("30 1 * * *", "America/New_York", "2026-11-01T06:00:00+00:00", "2026-11-02T06:30:00+00:00"),
    ("* * * * *", "America/New_York", "2026-11-01T05:59:00+00:00", "2026-11-01T07:00:00+00:00"),
    ("15 2 * * *", "Australia/Lord_Howe", "2026-10-03T15:29:59+00:00", "2026-10-04T15:15:00+00:00"),
    ("0 12 * * *", "Pacific/Apia", "2011-12-29T22:00:00+00:00", "2011-12-30T22:00:00+00:00"),
    ("0 9 * * *", "Asia/Yekaterinburg", "2026-11-14T04:00:00+00:00", "2026-11-15T04:00:00+00:00"),
])
def test_cron_slot_uses_wall_clock_and_only_the_first_fall_occurrence(expression, zone, after, expected):
    slot = next_cron_slot(expression, zone, datetime.fromisoformat(after))
    assert slot == datetime.fromisoformat(expected)
    assert slot.tzinfo is timezone.utc


def test_interval_duration_is_utc_and_uses_strictly_future_slots_after_backlog():
    anchor = datetime.fromisoformat("2026-11-01T05:30:00+00:00")
    after = datetime.fromisoformat("2026-11-01T07:05:00+00:00")
    schedule = Schedule(interval_seconds=3600, timezone="America/New_York")
    assert next_schedule_slot(schedule, after, interval_anchor=anchor) == datetime.fromisoformat(
        "2026-11-01T07:30:00+00:00",
    )


def test_one_shot_keeps_the_explicit_offset_in_a_repeated_wall_time():
    after = datetime.fromisoformat("2026-11-01T05:31:00+00:00")
    schedule = Schedule(
        one_shot_at=datetime.fromisoformat("2026-11-01T01:30:00-05:00"),
        timezone="America/New_York",
    )
    assert next_schedule_slot(schedule, after) == datetime.fromisoformat("2026-11-01T06:30:00+00:00")


def test_active_window_includes_its_exact_start_and_end():
    after = datetime.fromisoformat("2026-11-01T04:00:00+00:00")
    start = datetime.fromisoformat("2026-11-01T04:15:00+00:00")
    end = datetime.fromisoformat("2026-11-01T04:30:00+00:00")
    schedule = Schedule(cron_expression="*/15 * * * *", active_from=start, active_until=end)
    assert next_schedule_slot(schedule, after) == start
    assert next_schedule_slot(schedule, start) == end
    assert next_schedule_slot(schedule, end) is None


def test_an_invalid_legacy_cron_stops_recalculating_without_raising():
    assert next_cron_slot("legacy invalid expression", "UTC", datetime.now(timezone.utc)) is None
