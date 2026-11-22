"""Camera-relative control for a verified foot route on the world map."""

import math
import time

import numpy as np

from scripts.pilot.world_map_lab.destination_itinerary import plan


class WalkTrip:
    def __init__(self, road, goal, surface):
        self.road, self.surface = road, surface
        self.goal = np.asarray(goal, dtype=float)
        if self.goal.shape != (3,) or not np.isfinite(self.goal).all():
            raise ValueError("invalid_goal")
        if not any(
            abs(z - self.goal[2]) < 0.45
            for z in road.levels(*self.goal[:2], mode="walk", surface="pavement")
        ):
            raise ValueError("unreachable_goal")
        self.last_use = time.monotonic()
        self.last_sequence = -1
        self.last_media_time = self.previous = self.motion_origin = None
        self.path = None
        self.last_plan = -math.inf
        self.next_search = -math.inf
        self.arrival = None
        self.arrived = False

    def decide(self, pose, now):
        reply = dict(
            mode="walk",
            stick=[0.0, 0.0],
            lookRadians=0.0,
            reason="position_unknown",
            pose=pose,
            remaining=None,
        )
        if self.path is not None:
            reply["path"] = self.path.tolist()
        if self.arrived:
            return dict(reply, reason="arrived", remaining=0.0)
        if pose is None:
            self.previous = self.arrival = None
            if self.motion_origin and now - self.motion_origin[0] > 1.2:
                self.motion_origin = None
            return reply
        eye = np.asarray(pose["eye"], dtype=float)
        heading = pose["heading"]
        prior = self.previous
        self.previous = now, eye, heading
        if not prior or not 0 < now - prior[0] <= 1.2:
            self.arrival = None
            return dict(reply, reason="confirming_position")
        dt = now - prior[0]
        change = math.dist(eye, prior[1])
        turn = math.remainder(heading - prior[2], math.tau)
        if change > 0.42 + 3.8 * dt or abs(turn) > 0.23 + 2.6 * dt:
            self.arrival = self.motion_origin = None
            return dict(reply, reason="confirming_position")
        speed = change / dt
        if self.path is None:
            if now - self.last_plan < 1.5:
                return dict(reply, reason="planning_walk")
            self.last_plan = now
            levels = self.road.levels(*eye[:2], mode="walk", surface="pavement")
            ground = [z for z in levels if 0.85 < eye[2] - z < 2.55]
            if len(ground) != 1:
                return dict(reply, reason="walk_start_not_on_pavement")
            start = [float(eye[0]), float(eye[1]), ground[0]]
            result = plan(self.road, [start, self.goal.tolist()], "walk", None, surface="crossings")
            if result["status"] != "complete":
                return dict(reply, reason="walk_path_unavailable")
            points = np.asarray(result["legs"][0]["path"], float)
            self.path = points[np.r_[True, np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1) > 1e-4]]
            self.segments = np.diff(self.path, axis=0)
            self.distances = np.linalg.norm(self.segments[:, :2], axis=1)
            self.arc = np.r_[0, np.cumsum(self.distances)]
            reply["path"] = self.path.tolist()
            return dict(reply, reason="planning_walk", remaining=float(self.arc[-1]))
        if (
            math.dist(eye[:2], self.goal[:2]) <= 0.9
            and 0.85 < eye[2] - self.goal[2] < 2.55
        ):
            self.motion_origin = None
            if speed > 1.0 or self.arrival is None:
                self.arrival = now
            self.arrived = now - self.arrival >= 0.38
            return dict(reply, reason="arrived" if self.arrived else "stopping", remaining=0.0)
        self.arrival = None
        if not len(self.segments):
            self.path = None
            return dict(reply, reason="walk_path_unavailable")
        u = np.clip(
            np.sum((eye[:2] - self.path[:-1, :2]) * self.segments[:, :2], axis=1)
            / self.distances**2, 0, 1
        )
        projected = self.path[:-1] + u[:, None] * self.segments
        distances = np.linalg.norm(projected[:, :2] - eye[:2], axis=1)
        lift = eye[2] - projected[:, 2]
        distances[(lift <= 0.85) | (lift >= 2.55)] = np.inf
        index = int(np.argmin(distances))
        if distances[index] > 1.35:
            self.path = self.motion_origin = None
            return dict(reply, path=[], reason="walk_outside_path")
        station = float(self.arc[index] + u[index] * self.distances[index])
        remaining = float(self.arc[-1] - station)
        start = np.array([*eye[:2], projected[index, 2]])
        aim = None
        for lookahead in (1.75, 1.05, 0.55):
            end = np.array([
                np.interp(min(self.arc[-1], station + lookahead), self.arc, col)
                for col in self.path.T
            ])
            # The path itself is validated against original pavement and
            # crossings. These short sweeps only choose an unobstructed aim
            # on that path rather than aiming across an inside corner.
            if math.dist(start[:2], end[:2]) >= 0.05 and self.surface.sweep(start, end) == (0, True):
                aim = end
                break
        if aim is None:
            self.motion_origin = None
            return dict(reply, reason="walk_clearance_unknown", remaining=remaining)
        delta = aim - start
        error = math.remainder(math.atan2(delta[1], delta[0]) - heading, math.tau)
        if abs(error) > 0.34:
            self.motion_origin = None
            return dict(reply, reason="walk_aligning", lookRadians=error, remaining=remaining)
        if self.motion_origin is None or math.dist(self.motion_origin[1], eye[:2]) >= 0.35:
            self.motion_origin = now, eye[:2].copy()
        elif now - self.motion_origin[0] >= 6:
            return dict(reply, reason="no_motion", remaining=remaining)
        pace = min(0.35, max(0.15, 0.26 * remaining)) * (1 - 0.32 * abs(error))
        return dict(
            reply,
            reason="walking",
            remaining=remaining,
            stick=[-pace * math.sin(error), -pace * math.cos(error)],
        )
