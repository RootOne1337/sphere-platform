"""Check short, transverse crossings against the original road and pavement geometry."""

import math

import numpy as np

from scripts.pilot.world_map_lab.pedestrian_clearance import continuous_floor


def surface_kind(point):
    def overlaps(kind):
        value = point.get(kind)
        return value is not None and abs(value - point["floor"]) < 0.40

    if overlaps("footpath") or overlaps("paving"):
        return "pavement"
    if overlaps("road"):
        return "road"
    return None


def road_width(profile, spacing):
    """Measure the marked road on both sides of the centre of a cross-section."""
    center = len(profile) // 2
    road = [q["road"] is not None and abs(q["road"] - q["referenceZ"]) < 0.65 for q in profile]
    if not road[center]:
        return 0.0, 0.0
    left = right = center
    while left > 0 and road[left - 1]:
        left -= 1
    while right + 1 < len(road) and road[right + 1]:
        right += 1
    return (center - left + 0.5) * spacing, (right - center + 0.5) * spacing


def transverse(crossing, measure, width_limit=22):
    offsets = np.diff(crossing, axis=0)
    length = np.linalg.norm(offsets[:, :2], axis=1).sum()
    a, b = crossing[0], crossing[-1]
    span = np.linalg.norm((b - a)[:2])
    if not 0.7 <= span <= width_limit or length > span * 1.2:
        return False
    middle = (a + b) / 2
    direction = (b - a)[:2] / span
    side = np.array([-direction[1], direction[0]])
    # The road must extend appreciably farther along its own axis. This rejects
    # following a lane and ambiguous diagonals through broad intersections.
    widths = []
    for degrees in (0, -45, 45):
        angle = math.radians(degrees)
        axis = math.cos(angle) * direction + math.sin(angle) * side
        distance = 1.6 * span
        offset = np.r_[axis * distance, 0.0]
        profile = measure(middle - offset, middle + offset, samples=49)["profile"]
        widths.append(sum(road_width(profile, distance / 24)))
    along_offset = np.r_[side * max(20.0, 1.6 * span), 0.0]
    along_profile = measure(middle - along_offset, middle + along_offset, samples=49)["profile"]
    along_widths = road_width(along_profile, np.linalg.norm(along_offset) / 24)
    across, oblique_left, oblique_right = widths
    return (
        0.55 * span <= across <= 1.25 * span
        and min(along_widths) >= max(11.0, 0.72 * across)
        and min(oblique_left, oblique_right) >= 0.85 * across
    )


def crossing_target(ground, entry, exit, measure):
    """Keep a walking command inside the previously verified crossing strip."""
    start = np.asarray(ground, dtype=float)
    beginning = np.asarray(entry, dtype=float)
    finish = np.asarray(exit, dtype=float)
    axis = (finish - beginning)[:2]
    length = np.linalg.norm(axis)
    if length < 0.7:
        return None
    direction = axis / length
    offset = (start - beginning)[:2]
    along = offset @ direction
    if not -0.75 <= along < length or np.linalg.norm(offset - direction * along) > 0.75:
        return None
    # The endpoint is rechecked along the actual predicted foot line, also after
    # a small lateral displacement from the planned line.
    check = measure(start, finish, samples=max(3, math.ceil((length - along) / 0.25) + 1))
    if check["bodyIntersections"] or not continuous_floor(check):
        return None
    kinds = [surface_kind(point) for point in check["profile"]]
    if None in kinds or kinds[-1] != "pavement":
        return None
    return finish


def verified_crossings(path, measure):
    """Return crossing entry and exit points, or None when any segment is unproven."""
    samples = []
    for a, b in zip(path[:-1], path[1:]):
        if np.linalg.norm(b[:2] - a[:2]) < 0.001:
            continue
        length = np.linalg.norm(b[:2] - a[:2])
        check = measure(a, b, samples=max(3, math.ceil(length / 0.35) + 1))
        if check["bodyIntersections"] or not continuous_floor(check):
            return None
        points = np.linspace(a, b, len(check["profile"]))
        samples.extend((surface_kind(row), point) for row, point in zip(check["profile"], points))
    if not samples or samples[0][0] != "pavement" or samples[-1][0] != "pavement":
        return None
    crossings = []
    road_start = None
    for i, (kind, _) in enumerate(samples):
        if kind == "road":
            if road_start is None:
                road_start = i - 1
        elif kind == "pavement":
            if road_start is not None:
                strip = np.array([point for _, point in samples[road_start : i + 1]])
                if not transverse(strip, measure):
                    return None
                crossings.append({"entry": strip[0].tolist(), "exit": strip[-1].tolist()})
                road_start = None
        else:
            return None
    return crossings
