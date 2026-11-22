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


def transverse_exit(start, end, profile, measure):
    """An already exposed pedestrian can leave the road by its nearby edge."""
    start, end = np.asarray(start, dtype=float), np.asarray(end, dtype=float)
    direction = (end - start)[:2]
    length = np.linalg.norm(direction)
    if not 0.5 <= length <= 5.0:
        return False
    kinds = list(map(surface_kind, profile))
    if len(kinds) < 2 or kinds[0] != "road" or kinds[-1] != "pavement" or None in kinds:
        return False
    first_pavement = kinds.index("pavement")
    if "road" in kinds[first_pavement:]:
        return False

    direction /= length
    side = np.array([-direction[1], direction[0]])

    def extents(axis, metres):
        offset = np.r_[axis * metres, 0.0]
        section = measure(start - offset, start + offset, samples=49)["profile"]
        return road_width(section, metres / 24)

    along = extents(side, 20.0)
    oblique = [extents((direction + sign * side) / math.sqrt(2), 8.0)[1] for sign in (-1, 1)]
    exit_distance = length * first_pavement / (len(kinds) - 1)
    return min(along) >= 7.0 and min(oblique) >= 0.9 * exit_distance


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


def verified_crossings(path, measure, *, on_unclassified=None):
    """Return crossing entry and exit points, or None when any segment is unproven."""
    crossings = []
    last_pavement = None
    strip = []
    for a, b in zip(path[:-1], path[1:]):
        if np.linalg.norm(b[:2] - a[:2]) < 0.001:
            continue
        length = np.linalg.norm(b[:2] - a[:2])
        check = measure(a, b, samples=max(3, math.ceil(length / 0.35) + 1))
        if check["bodyIntersections"] or not continuous_floor(check):
            return None
        points = np.linspace(a, b, len(check["profile"]))
        for row, point in zip(check["profile"], points):
            kind = surface_kind(row)
            if kind == "pavement":
                if strip:
                    strip.append(point)
                    if not transverse(np.asarray(strip), measure):
                        return None
                    crossings.append({"entry": strip[0].tolist(), "exit": point.tolist()})
                    strip.clear()
                last_pavement = point
            elif kind == "road" and last_pavement is not None:
                if not strip:
                    strip.append(last_pavement)
                strip.append(point)
            else:
                if kind is None and on_unclassified:
                    on_unclassified(point)
                return None
    return crossings if last_pavement is not None and not strip else None
