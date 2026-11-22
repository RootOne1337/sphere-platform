"""Evaluate the footprint, height and landing of a short on-foot maneuver."""

from scripts.pilot.world_map_lab.survey_clearance import measure


def continuous_floor(row):
    return bool(row["profile"]) and all(
        q["floor"] is not None
        and abs(q["floor"] - q["referenceZ"]) < 0.40
        and (q["water"] is None or q["water"] < q["floor"] - 0.05)
        for q in row["profile"]
    )


def jumpable(obstacle, landing):
    if not obstacle["bodyIntersections"] or not continuous_floor(obstacle):
        return False
    begin = obstacle["blockedFrom"]
    end = obstacle["blockedTo"]
    return (
        begin is not None
        and end is not None
        and 0.1 <= begin <= end <= 1.85
        and end - begin <= 1.05
        and 0.30 <= obstacle["blockingHeight"] <= 0.82
        and landing["bodyIntersections"] == 0
        and continuous_floor(landing)
    )


def can_jump(start, end, direction, data, index, chunks, origin):
    args = (data, index, chunks, origin)
    obstacle = measure(dict(a=start, b=end, mode="walk"), *args)
    exit_at = obstacle["blockedTo"]
    if exit_at is None or exit_at > 1.85:
        return False
    landing = measure(dict(a=start + direction * (exit_at + 0.35), b=end, mode="walk"), *args)
    return jumpable(obstacle, landing)
