"""Calculate schedule slots with a shared wall-clock and UTC policy."""

from datetime import datetime, timedelta, timezone

import pytz
from croniter import CroniterBadCronError, CroniterBadDateError, croniter

from backend.models.schedule import Schedule


def advance_schedule_revision(previous: datetime) -> datetime:
    """Generate a strictly newer revision even after a lock wait or clock adjustment."""
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    return max(datetime.now(timezone.utc), previous + timedelta(microseconds=1))


def next_cron_slot(expression: str, timezone_name: str, after: datetime) -> datetime | None:
    """Skip nonexistent wall times and use the earlier instant of repeated wall times."""
    try:
        zone = pytz.timezone(timezone_name)
    except pytz.UnknownTimeZoneError:
        zone = pytz.UTC
    try:
        candidates = croniter(expression, after.astimezone(zone).replace(tzinfo=None))
    except CroniterBadCronError:
        return None
    while True:
        try:
            wall_time = candidates.get_next(datetime)
        except CroniterBadDateError:
            return None
        try:
            instant = zone.localize(wall_time, is_dst=None).astimezone(timezone.utc)
        except pytz.NonExistentTimeError:
            continue
        except pytz.AmbiguousTimeError:
            instant = min(
                zone.localize(wall_time, is_dst=True).astimezone(timezone.utc),
                zone.localize(wall_time, is_dst=False).astimezone(timezone.utc),
            )
        if instant > after:
            return instant


def next_schedule_slot(
    schedule: Schedule, after: datetime, *, interval_anchor: datetime | None = None,
) -> datetime | None:
    """Return the first slot strictly after the reference, within the active window."""
    if schedule.is_active is False:
        return None
    if schedule.max_runs is not None and (schedule.total_runs or 0) >= schedule.max_runs:
        return None
    if schedule.active_from is not None and schedule.active_from > after:
        after = schedule.active_from - timedelta(microseconds=1)
    if schedule.active_until is not None and after >= schedule.active_until:
        return None

    if schedule.cron_expression:
        next_fire = next_cron_slot(schedule.cron_expression, schedule.timezone or "UTC", after)
    elif schedule.interval_seconds:
        period = timedelta(seconds=schedule.interval_seconds)
        anchor = interval_anchor or schedule.last_fired_at or after
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        periods = max(1, (after - anchor) // period + 1)
        next_fire = (anchor + periods * period).astimezone(timezone.utc)
    elif schedule.one_shot_at:
        next_fire = schedule.one_shot_at
        if next_fire.tzinfo is None:
            next_fire = next_fire.replace(tzinfo=timezone.utc)
        next_fire = next_fire.astimezone(timezone.utc)
        if next_fire <= after:
            return None
    else:
        return None
    if next_fire is not None and schedule.active_until is not None and next_fire > schedule.active_until:
        return None
    return next_fire
