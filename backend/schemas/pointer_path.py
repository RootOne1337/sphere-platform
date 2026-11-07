"""Bounded single-finger trajectory, validated before any native input."""
from __future__ import annotations

import json


def valid_pointer_path(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"schema_version", "frame_width", "frame_height", "points"}:
        return False
    integer = lambda n: isinstance(n, int) and not isinstance(n, bool)  # noqa: E731
    if not integer(value["schema_version"]) or value["schema_version"] != 1:
        return False
    width, height, points = value["frame_width"], value["frame_height"], value["points"]
    if not all(integer(n) and 1 <= n <= 16384 for n in (width, height)):
        return False
    if not isinstance(points, list) or not 2 <= len(points) <= 4096:
        return False
    previous = 0
    for index, point in enumerate(points):
        if not isinstance(point, dict) or set(point) != {"t_ms", "action", "x", "y"}:
            return False
        if not all(integer(n) for n in point.values()):
            return False
        at = point["t_ms"]
        expected = 0 if index == 0 else 1 if index == len(points) - 1 else 2
        if not previous <= at <= 60000 or index == 0 and at != 0 or point["action"] != expected:
            return False
        if not 0 <= point["x"] < width or not 0 <= point["y"] < height:
            return False
        previous = at
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()) <= 256 * 1024


def requires_pointer_path(value: object) -> bool:
    """Includes nested loop actions; no task producer may bypass version admission."""
    if isinstance(value, dict):
        return value.get("type") == "pointer_path" or any(requires_pointer_path(item) for item in value.values())
    return isinstance(value, list) and any(requires_pointer_path(item) for item in value)


def pointer_path_admission_error(dag: object, agent_version_code: int | None) -> str | None:
    if requires_pointer_path(dag) and (agent_version_code or 0) < 10281:
        return "pointer_path requires Android agent 1.2.81+; no input was sent"
    return None
