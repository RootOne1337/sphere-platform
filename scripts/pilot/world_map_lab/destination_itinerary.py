"""Ordered stops on the typed Detour road and pedestrian surfaces."""

import math

MODES = {"drive", "walk", "taxi"}
MAX_STOPS = 18


def fmt(point):
    return ",".join(format(v, ".8f") for v in point)


def plan(road, stops, mode, covers, *, surface=None):
    if mode not in MODES or not isinstance(stops, list) or not 2 <= len(stops) <= MAX_STOPS:
        raise ValueError("invalid_goal")
    if surface is not None and (mode != "walk" or surface not in ("pavement", "crossings")):
        raise ValueError("invalid_goal")
    mesh = "drive" if mode == "drive" else "walk"
    level_filter = {"surface": "pavement"} if surface else {}
    path_filter = {"surface": surface} if surface else {}
    legs = []
    distance = 0.0
    covered = mode == "drive"
    for i, point in enumerate(stops):
        if (
            not isinstance(point, list)
            or len(point) != 3
            or not all(type(v) in (int, float) and math.isfinite(v) for v in point)
        ):
            raise ValueError("invalid_goal")
        if not any(
            abs(point[2] - z) < 0.45 for z in road.levels(*point[:2], mode=mesh, **level_filter)
        ):
            return dict(status="unavailable", reason="wrong_surface", stop=i, legs=[])
    for i, (a, b) in enumerate(zip(stops, stops[1:])):
        result = road.query("path", mode=mode, start=fmt(a), end=fmt(b), **path_filter)
        pieces = (
            result.get("legs", [])
            if mode == "taxi"
            else [dict(mode=mode, path=result.get("path", []))]
        )
        if result.get("status") != "complete" or not pieces:
            reason = "surface_unconfirmed" if surface and result["status"] == "surface_unconfirmed" else "no_path"
            return dict(status="unavailable", reason=reason, stop=i + 1, legs=[])
        prev = a
        for leg in pieces:
            path = leg.get("path", [])
            if not path or math.dist(prev, path[0]) > 2.5 or leg["mode"] not in ("walk", "drive"):
                return dict(status="unavailable", reason="endpoint_off_road", stop=i + 1, legs=[])
            length = sum(math.dist(x, y) for x, y in zip(path, path[1:]))
            item = dict(mode=leg["mode"], path=path, distance=length, fromIndex=i)
            if result.get("crossings"):
                item["crossings"] = result["crossings"]
            legs.append(item)
            distance += length
            covered = covered and covers(path)
            prev = path[-1]
        if math.dist(prev, b) > 2.5:
            return dict(status="unavailable", reason="endpoint_off_road", stop=i + 1, legs=[])
    return dict(status="complete", legs=legs, distance=distance, covered=bool(covered))
