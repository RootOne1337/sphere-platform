"""Check a short scooter connection from a walkable shoulder using original world collisions."""

import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.destination_itinerary import fmt
from scripts.pilot.world_map_lab.survey_clearance import measure
from scripts.pilot.world_map_lab.world_navmesh import spatial_index


class RoadAccess:
    def __init__(self, folder: Path, road):
        self.road = road
        source = folder / "world-geometry.bin"
        with source.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != road.meta["geometrySha256"]:
                raise ValueError("access collision geometry mismatch")
        self.data = np.memmap(source, dtype="u1", mode="r")
        bounds = road.meta["bounds"]
        self.origin = (bounds[0], bounds[3])
        self.index, self.chunks = spatial_index(self.data, bounds)
        with np.load(folder / "drive-faces.npz", allow_pickle=False) as archive:
            if str(archive["geometry"]) != road.meta["geometrySha256"]:
                raise ValueError("road surface geometry mismatch")
            faces = archive["faces"]
        vertices, count = faces["xyz"], faces["vertices"]
        valid = np.arange(vertices.shape[1])[None, :, None] < count[:, None, None]
        self.centers = np.where(valid, vertices, 0).sum(axis=1) / count[:, None]
        self.tree = cKDTree(self.centers[:, :2])
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-road-access")

    def clear(self, a, b):
        delta = b[:2] - a[:2]
        span = np.linalg.norm(delta)
        if span < 0.01:
            return abs(a[2] - b[2]) <= 0.1
        if abs(a[2] - b[2]) > 0.22 + 0.23 * span:
            return False
        side = np.array([-delta[1], delta[0], 0]) / span
        for width in (0, -0.35, 0.35):
            offset = width * side
            row = measure(
                dict(a=a + offset, b=b + offset, mode="drive"),
                self.data,
                self.index,
                self.chunks,
                self.origin,
            )
            if row["bodyIntersections"] or any(
                p["floor"] is None
                or abs(p["floor"] - p["referenceZ"]) > 0.32
                or (p["water"] is not None and p["water"] >= p["floor"] - 0.05)
                for p in row["profile"]
            ):
                return False
        return True

    def find(self, eye, goal):
        levels = [z for z in self.road.levels(*eye[:2], mode="walk") if 0.5 < eye[2] - z < 2.7]
        if len(levels) != 1:
            return None
        start = np.array([*eye[:2], levels[0]])
        ids = self.tree.query_ball_point(start[:2], 35)
        nearby = sorted(
            (self.centers[i] for i in ids if abs(self.centers[i, 2] - start[2]) < 1.3),
            key=lambda p: np.linalg.norm(p - start),
        )
        tried = []
        for point in nearby:
            if any(math.dist(p[:2], point[:2]) < 3 for p in tried):
                continue
            if len(tried) == 24:
                break
            tried.append(point)
            walk = self.road.query("path", mode="walk", start=fmt(start), end=fmt(point))
            lead = np.asarray(walk.get("path", []))
            if (
                walk.get("status") != "complete"
                or len(lead) < 2
                or walk["length"] > 42
                or math.dist(lead[0], start) > 0.5
                or math.dist(lead[-1], point) > 1.2
            ):
                continue
            drive = self.road.route(point, goal)
            lane = np.asarray(drive.get("path", []))
            if (
                drive.get("status") != "complete"
                or len(lane) < 2
                or math.dist(lane[0], point) > 1.2
                or math.dist(lane[-1], goal) > 2.5
            ):
                continue
            prefix = np.vstack((lead, lane[:1]))
            if all(self.clear(a, b) for a, b in zip(prefix, prefix[1:])):
                return dict(
                    status="complete",
                    path=np.vstack((lead, lane)).tolist(),
                    accessMeters=float(np.linalg.norm(np.diff(prefix, axis=0), axis=1).sum()),
                )
        return None
