"""Infer transfer actions from a first-person camera and a walk/drive/walk itinerary."""

import math
from collections import deque

import numpy as np


class MixedJourney:
    def __init__(self, paths):
        self.walks = [np.asarray(paths[n], float) for n in (0, 2)]
        self.bike = np.asarray(paths[1][0], float)
        self.park = np.asarray(paths[1][-1], float)
        road = np.asarray(paths[1], float)
        direction = next(
            p[:2] - self.bike[:2] for p in road[1:] if np.linalg.norm(p[:2] - self.bike[:2]) > 0.5
        )
        self.bike_heading = direction / np.linalg.norm(direction)
        self.stage = "approach"
        self.saw_start = False
        self.samples = deque()
        self.transfer = None
        self.previous = None

    def change(self, stage):
        self.stage = stage
        self.samples.clear()

    def still(self, t, p, method, heading):
        self.samples.append((t, p.copy(), method, heading.copy()))
        while self.samples and t - self.samples[0][0] > 1.5:
            self.samples.popleft()
        return (
            len(self.samples) >= 3
            and t - self.samples[0][0] >= 0.6
            and any(item[2] == "matched" for item in self.samples)
            and all(np.linalg.norm(x[1] - p) < 0.40 and x[3] @ heading > 0.96 for x in self.samples)
        )

    def walk(self, path, eye, heading):
        # Ignore vertical camera-to-ground offset for steering; retain the layer check in step.
        segs = np.diff(path[:, :2], axis=0)
        lengths = np.linalg.norm(segs, axis=1)
        where = np.clip(
            np.sum((eye[:2] - path[:-1, :2]) * segs, axis=1) / np.maximum(lengths**2, 1e-8),
            0.0,
            1.0,
        )
        dist = np.linalg.norm(path[:-1, :2] + where[:, None] * segs - eye[:2], axis=1)
        i = int(np.argmin(dist))
        if dist[i] > 2.75:
            return [], 0.0
        arc = np.r_[0.0, np.cumsum(lengths)]
        station = min(arc[-1], arc[i] + where[i] * lengths[i] + 1.5)
        aim = np.array([np.interp(station, arc, col) for col in path[:, :2].T]) - eye[:2]
        yaw = math.atan2(heading[1] * aim[0] - heading[0] * aim[1], heading @ aim)
        return (["W"] if abs(yaw) < 0.95 else []), float(np.clip(yaw * 0.60, -0.35, 0.35))

    def step(self, row, fit, reset_driver):
        """Visual completion is a hypothesis. The compiled native observer judges actual success."""
        row.update(journey_phase=self.stage, keys=[], walk_turn=0.0, goal_seen=False)
        if fit is None or row["latency_ms"] >= 250:
            self.previous = None
            self.samples.clear()
            return
        eye, rotation, _, _, _ = fit
        head = rotation[2, :2].copy()
        norm = np.linalg.norm(head)
        if norm < 0.60:
            self.samples.clear()
            return
        head /= norm
        t = row["capture_s"]
        previous = self.previous
        self.previous = (t, eye.copy())
        if (
            previous is None
            or not 0 < t - previous[0] <= 0.50
            or np.linalg.norm(eye - previous[1])
            > 0.7 + (t - previous[0]) * (16 if self.stage == "drive" else 5)
        ):
            self.samples.clear()
            return
        if self.samples and t - self.samples[-1][0] > 0.50:
            self.samples.clear()
        if self.stage == "drive":
            if row["phase"] == "arrived" and np.linalg.norm(eye[:2] - self.park[:2]) <= 2.1:
                self.change("park")
            return
        if self.stage in ("approach", "depart"):
            path = self.walks[0 if self.stage == "approach" else 1]
            if abs(eye[2] - path[-1, 2] - 1.5) > 1.6:
                return
            if self.stage == "approach" and np.linalg.norm(eye[:2] - path[0, :2]) <= 1.6:
                self.saw_start = True
            if self.stage == "approach" and not self.saw_start:
                return
            near = np.linalg.norm(eye[:2] - path[-1, :2]) <= (
                1.45 if self.stage == "approach" else 0.9
            )
            if not near:
                self.samples.clear()
                row["keys"], row["walk_turn"] = self.walk(path, eye, head)
            elif self.still(t, eye, row["vision"], head):
                if self.stage == "approach":
                    self.transfer = (eye.copy(), head.copy(), t)
                    self.change("boarding")
                    row["keys"] = ["F"]
                else:
                    self.change("goal_observed")
                    row["goal_seen"] = True
        elif self.stage == "park":
            if np.linalg.norm(eye[:2] - self.park[:2]) <= 2.1 and self.still(
                t, eye, row["vision"], head
            ):
                self.transfer = (eye.copy(), head.copy(), t)
                self.change("exiting")
                row["keys"] = ["F"]
        elif self.stage in ("boarding", "exiting"):
            origin, old_head, start = self.transfer
            near = self.bike if self.stage == "boarding" else self.park
            moved = np.linalg.norm(eye - origin) > 0.42 or head @ old_head < 0.90
            common = (
                t - start > 0.7
                and moved
                and np.linalg.norm(eye[:2] - near[:2]) < 2.55
                and abs(eye[2] - near[2] - 1.5) < 1.6
            )
            if common and (self.stage != "boarding" or head @ self.bike_heading > 0.90):
                if self.still(t, eye, row["vision"], head):
                    if self.stage == "boarding":
                        reset_driver()
                        self.change("drive")
                    else:
                        self.change("depart")
            else:
                self.samples.clear()
        row["journey_phase"] = self.stage
