"""Local steering against the same source solids and walking floors as the world route."""

import math
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.destination_itinerary import fmt
from scripts.pilot.world_map_lab.pedestrian_clearance import can_jump, continuous_floor
from scripts.pilot.world_map_lab.survey_clearance import measure
from scripts.pilot.world_map_lab.world_navmesh import spatial_index


class FootSurface:
    def __init__(self, folder, road):
        self.road = road
        geometry = Path(folder) / "world-geometry.bin"
        self.data = np.memmap(geometry, dtype="u1", mode="r")
        bounds = road.meta["bounds"]
        self.index, self.chunks = spatial_index(self.data, bounds)
        self.origin = bounds[0], bounds[3]

    def sweep(self, start, end):
        row = measure(
            dict(a=start, b=end, mode="walk"), self.data, self.index, self.chunks, self.origin
        )
        return row["bodyIntersections"], continuous_floor(row)

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

    def connection(self, eye, goal, expected):
        start = np.array([*eye[:2], expected])
        for radius in (0, 0.75, 1.5, 2.5, 4, 5.5):
            paths = []
            for angle in np.linspace(0, 2 * math.pi, 12 if radius else 1, endpoint=False):
                xy = start[:2] + radius * np.array([math.cos(angle), math.sin(angle)])
                levels = self.road.levels(*xy, mode="walk")
                heights = sorted(
                    (z for z in levels if 0.35 < eye[2] - z < 2.8), key=lambda z: abs(z - expected)
                )
                for z in heights[:2]:
                    ground = np.array([*xy, z])
                    if radius and not self.clear_or_exiting(start, ground):
                        continue
                    route = self.road.query("path", mode="walk", start=fmt(ground), end=fmt(goal))
                    if route.get("status") != "complete" or not route.get("path"):
                        continue
                    if math.dist(route["path"][0], ground) < 0.9:
                        path = [start.tolist(), *route["path"]] if radius else route["path"]
                        paths.append((route["length"] + math.dist(start, ground), path))
            if paths:
                return min(paths, key=lambda pair: pair[0])[1]
        return None

    def aim(self, eye, height, target, avoid_bias=0):
        start = np.array([*eye[:2], eye[2] - height])
        offset = np.asarray(target) - start[:2]
        heading = math.atan2(offset[1], offset[0])
        lookahead = min(max(1.0, np.linalg.norm(offset)), 3.0)
        side = 1 if avoid_bias >= 0 else -1
        for turn in (0, 0.38, -0.38, 0.74, -0.74, 1.18, -1.18, 1.58, -1.58, 2.13, -2.13, math.pi):
            angle = heading + turn * side
            end = start + lookahead * np.array([math.cos(angle), math.sin(angle), 0])
            levels = self.road.levels(*end[:2], mode="walk")
            nearby = [z for z in levels if abs(z - start[2]) < 0.55]
            if nearby:
                end[2] = min(nearby, key=lambda z: abs(start[2] - z))
                if self.clear_or_exiting(start, end):
                    return end[:2]
        return None

    def low_barrier(self, eye, height, heading):
        start = np.array([*eye[:2], eye[2] - height])
        direction = np.array([math.cos(heading), math.sin(heading), 0])
        end = start + 2.9 * direction
        if not any(abs(z - start[2]) < 0.3 for z in self.road.levels(*end[:2], mode="walk")):
            return False
        return can_jump(start, end, direction, self.data, self.index, self.chunks, self.origin)
