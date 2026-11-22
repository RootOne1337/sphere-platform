"""Local steering against the same source solids and walking floors as the world route."""

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.destination_itinerary import fmt
from scripts.pilot.world_map_lab.pedestrian_clearance import (
    can_jump,
    continuous_floor,
    continuous_pavement,
)
from scripts.pilot.world_map_lab.pedestrian_crossing import (
    crossing_target,
    surface_kind,
    transverse_exit,
    verified_crossings,
)
from scripts.pilot.world_map_lab.pedestrian_scene import plausible_walk_height
from scripts.pilot.world_map_lab.pedestrian_visibility import PedestrianVisibility
from scripts.pilot.world_map_lab.survey_clearance import measure
from scripts.pilot.world_map_lab.world_navmesh import spatial_index


@dataclass(frozen=True)
class GroundSupport:
    height: float
    on_mesh: bool


class FootSurface:
    pavement = False

    def __init__(self, folder, road, *, pavement=False, check_visibility=True):
        self.road = road
        self.pavement = pavement
        geometry = Path(folder) / "world-geometry.bin"
        self.data = np.memmap(geometry, dtype="u1", mode="r")
        bounds = road.meta["bounds"]
        self.index, self.chunks = spatial_index(self.data, bounds)
        self.origin = bounds[0], bounds[3]
        detail = Path(folder) / "detail-scene.sqlite"
        self.visibility = (
            PedestrianVisibility(detail, road.meta["placementRevision"])
            if check_visibility and detail.is_file()
            else None
        )

    def close(self):
        if self.visibility:
            self.visibility.close()

    def _measure(self, start, end, *, samples=17):
        return measure(
            dict(a=start, b=end, mode="walk", samples=samples),
            self.data,
            self.index,
            self.chunks,
            self.origin,
        )

    def sweep(self, start, end):
        row = self._measure(start, end)
        supported = continuous_pavement(row) if self.pavement else continuous_floor(row)
        return row["bodyIntersections"], supported

    def paved_route(self, path):
        points = np.asarray(path, dtype=float)
        if points.shape == (1, 3):
            return self.sweep(points[0], points[0]) == (0, True)
        return len(points) > 1 and all(
            self.sweep(a, b) == (0, True) for a, b in zip(points[:-1], points[1:])
        )

    def crossings_on(self, path):
        return verified_crossings(np.asarray(path, dtype=float), self._measure)

    def crossing_aim(self, eye, height, crossing):
        start = np.array([*eye[:2], eye[2] - height])
        return crossing_target(start, crossing["entry"], crossing["exit"], self._measure)

    def ground_support(self, eye, camera_height):
        """Use the original floor to confirm a pose just outside the eroded walk mesh."""
        expected = eye[2] - camera_height
        levels = self.road.levels(*eye[:2], mode="walk")
        if levels:
            close = [z for z in levels if plausible_walk_height(eye[2], (z,))]
            return (
                GroundSupport(min(close, key=lambda z: abs(z - expected)), True) if close else None
            )
        point = np.array([*eye[:2], expected])
        sample = self._measure(point, point)["profile"][0]
        level = sample["floor"]
        if level is None or not plausible_walk_height(eye[2], (level,)):
            return None
        if abs(level - expected) >= 0.40 or (
            sample["water"] is not None and sample["water"] >= level - 0.05
        ):
            return None
        return GroundSupport(level, False)

    def clear_or_exiting(self, start, end):
        hits, dry = self.sweep(start, end)
        if not dry or not hits:
            return dry
        distance = np.linalg.norm((end - start)[:2])
        if distance < 0.05:
            return False
        direction = (end - start) / distance
        count, dry = self.sweep(start, start + 0.04 * direction)
        if not dry or not count:
            return False
        # A noisy initial pose can overlap foliage. Permit a short exit only if
        # contact diminishes and the remaining corridor is completely clear.
        for offset in np.linspace(0, min(distance, 1.0), 11)[1:]:
            point = start + offset * direction
            probe = start + min(offset + 0.04, distance) * direction
            remaining, dry = self.sweep(point, probe)
            if not dry or remaining > count:
                return False
            if remaining == 0:
                hits, dry = self.sweep(point, end)
                return dry and hits == 0
            count = remaining
        return False

    def connection(self, eye, goal, expected, *, heading=None):
        start = np.array([*eye[:2], expected])
        for radius in (0, 0.35, 0.75, 1.5, 2.5, 4, 5.5):
            paths = []
            for angle in np.linspace(0, 2 * math.pi, 12 if radius else 1, endpoint=False):
                xy = start[:2] + radius * np.array([math.cos(angle), math.sin(angle)])
                levels = self.road.levels(*xy, mode="walk")
                heights = sorted(
                    (z for z in levels if 0.35 < eye[2] - z < 2.8), key=lambda z: abs(z - expected)
                )
                for z in heights[:2]:
                    ground = np.array([*xy, z])
                    policy = {"surface": "pavement"} if self.pavement else {}
                    route = self.road.query(
                        "path", mode="walk", start=fmt(ground), end=fmt(goal), **policy
                    )
                    if route.get("status") != "complete" or not route.get("path"):
                        continue
                    entry = np.asarray(route["path"][0])
                    distance = math.dist(start, entry)
                    if math.dist(entry, ground) >= 0.9 or not self.clear_or_exiting(start, entry):
                        continue
                    path = [start.tolist(), *route["path"]] if distance > 0.001 else route["path"]
                    turn_cost = 0
                    if heading is not None and distance >= 0.10:
                        bearing = math.atan2(entry[1] - start[1], entry[0] - start[0])
                        turn_cost = 0.5 * abs(math.remainder(bearing - heading, 2 * math.pi))
                    paths.append((route["length"] + distance + turn_cost, path))
            if paths:
                return min(paths, key=lambda pair: pair[0])[1]
        return None

    def pavement_entries(self, eye, goal, camera_height=1.55):
        """Find short, dry approaches, with transverse egress if already on the road."""
        support = self.ground_support(eye, camera_height)
        if support is None or not support.on_mesh:
            return
        start = [float(eye[0]), float(eye[1]), support.height]
        heading = math.atan2(goal[1] - start[1], goal[0] - start[0])
        profile = self._measure(start, start)["profile"]
        on_road = continuous_floor({"profile": profile}) and surface_kind(profile[0]) == "road"
        samples = 24 if on_road else 12
        directions = sorted(
            (index * math.tau / samples for index in range(samples)),
            key=lambda angle: abs(math.remainder(angle - heading, math.tau)),
        )
        radii = (0.65, 1.25, 2.25, 3.0, 3.5, 4.0, 4.5, 5.0) if on_road else (
            0.65, 1.25, 2.25, 3.5, 5.0
        )
        for radius in radii:
            for angle in directions:
                x = start[0] + radius * math.cos(angle)
                y = start[1] + radius * math.sin(angle)
                for level in self.road.levels(x, y, mode="walk", surface="pavement"):
                    if abs(level - start[2]) > 0.40:
                        continue
                    end = [x, y, level]
                    row = self._measure(start, end)
                    if row["bodyIntersections"] or not continuous_floor(row):
                        continue
                    if any(surface_kind(p) == "road" for p in row["profile"]):
                        if not transverse_exit(start, end, row["profile"], self._measure):
                            continue
                    yield start, end

    def step_supported(self, start, end):
        offset = (end - start)[:2]
        distance = np.linalg.norm(offset)
        if distance < 0.05:
            return False
        target = start[:2] + min(0.45, distance) / distance * offset
        step = self.road.query("step", mode="walk", start=fmt(start), xy=fmt(target))
        return step["moved"] and math.dist(step["position"][:2], target) < 0.12

    def pavement_aim(self, eye, height, route_targets):
        start = np.array([*eye[:2], eye[2] - height])
        # Try the farthest reachable point first. At a tight bend, reduce the
        # lookahead along the route instead of steering across the corner.
        for end in route_targets:
            end = np.asarray(end, dtype=float)
            if np.linalg.norm(end[:2] - start[:2]) < 0.05:
                continue
            if self.visibility and self.visibility.exposure(eye, end) > 0.12:
                continue
            if self.sweep(start, end) == (0, True):
                return end[:2]
        return None

    def aim(self, eye, height, target, avoid_bias=0):
        start = np.array([*eye[:2], eye[2] - height])
        offset = np.asarray(target) - start[:2]
        heading = math.atan2(offset[1], offset[0])
        lookahead = min(np.linalg.norm(offset), 3.0)
        if lookahead < 0.05:
            return None
        side = 1 if avoid_bias >= 0 else -1
        best_cost, best = math.inf, None
        for turn in (0, 0.38, -0.38, 0.74, -0.74, 1.18, -1.18, 1.58, -1.58, 2.13, -2.13, math.pi):
            direction_cost = 0.18 * abs(turn)
            if direction_cost >= best_cost:
                break
            angle = heading + turn * side
            end = start + lookahead * np.array([math.cos(angle), math.sin(angle), 0])
            levels = self.road.levels(*end[:2], mode="walk")
            nearby = [z for z in levels if abs(z - start[2]) < 0.55]
            if nearby:
                end[2] = min(nearby, key=lambda z: abs(start[2] - z))
                if self.clear_or_exiting(start, end):
                    exposure = self.visibility.exposure(eye, end) if self.visibility else 0
                    cost = direction_cost + 4 * exposure
                    if cost < best_cost:
                        best_cost, best = cost, end[:2]
        return best

    def low_barrier(self, eye, height, heading):
        if self.pavement:
            return False
        start = np.array([*eye[:2], eye[2] - height])
        direction = np.array([math.cos(heading), math.sin(heading), 0])
        end = start + 2.9 * direction
        if not any(abs(z - start[2]) < 0.3 for z in self.road.levels(*end[:2], mode="walk")):
            return False
        return can_jump(start, end, direction, self.data, self.index, self.chunks, self.origin)
