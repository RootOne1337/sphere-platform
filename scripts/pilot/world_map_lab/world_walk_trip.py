"""Camera-relative control for a verified foot route on the world map."""

import math
import time
from itertools import islice

import numpy as np

from scripts.pilot.world_map_lab.destination_itinerary import MAX_STOPS, plan


class WalkTrip:
    def __init__(self, road, goal, surface, *, next_stops=()):
        self.road, self.surface = road, surface
        self.stops = [self.validated_stop(stop) for stop in (goal, *next_stops)]
        self.stop_index = 0
        self.goal = self.stops[0]
        self.last_use = time.monotonic()
        self.last_sequence = -1
        self.last_media_time = self.previous = self.motion_origin = None
        self.path = None
        self.crossings = ()
        self.entry = None
        self.last_plan = -math.inf
        self.next_search = -math.inf
        self.pose_bank = None
        self.normalized_pose_bank = False
        self.last_visual_fix = None
        self.arrival = None
        self.arrived = False

    @classmethod
    def from_stops(cls, road, stops, surface):
        if not isinstance(stops, list) or not 1 <= len(stops) <= MAX_STOPS:
            raise ValueError("invalid_goal")
        return cls(road, stops[0], surface, next_stops=stops[1:])

    def validated_stop(self, stop):
        point = np.asarray(stop, dtype=float)
        if point.shape != (3,) or not np.isfinite(point).all():
            raise ValueError("invalid_goal")
        if not any(
            abs(z - point[2]) < 0.45
            for z in self.road.levels(*point[:2], mode="walk", surface="pavement")
        ):
            raise ValueError("unreachable_goal")
        return point

    def pavement_below(self, eye):
        levels = self.road.levels(*eye[:2], mode="walk", surface="pavement")
        return [z for z in levels if 0.85 < eye[2] - z < 2.55]

    def decide(self, pose, now):
        reply = dict(
            mode="walk",
            stick=[0.0, 0.0],
            lookRadians=0.0,
            reason="position_unknown",
            pose=pose,
            remaining=None,
            stopIndex=self.stop_index,
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
            ground = self.pavement_below(eye)
            if len(ground) > 1:
                return dict(reply, reason="walk_start_not_on_pavement")
            goal = self.goal.tolist()
            if ground:
                start = [float(eye[0]), float(eye[1]), ground[0]]
                start_options = [(None, start)]
            else:
                start_options = islice(self.surface.pavement_entries(eye, goal), 4)
            points = None
            found_entry = False
            for connector, start in start_options:
                found_entry = True
                result = plan(self.road, [start, goal], "walk", None, surface="crossings")
                if result["status"] != "complete":
                    continue
                leg = result["legs"][0]
                path = leg["path"]
                if connector is not None:
                    if math.dist(start, path[0]) >= 0.45:
                        continue
                    path = [connector, start, *path]
                self.entry = np.asarray([connector, start], float) if connector is not None else None
                self.crossings = tuple(
                    np.asarray(strip.get("path", [strip["entry"], strip["exit"]]), float)
                    for strip in leg.get("crossings", ())
                )
                points = np.asarray(path, float)
                break
            if points is None:
                return dict(reply, reason="walk_path_unavailable" if found_entry else "walk_start_not_on_pavement")
            self.path = points[np.r_[True, np.linalg.norm(np.diff(points[:, :2], axis=0), axis=1) > 1e-4]]
            self.segments = np.diff(self.path, axis=0)
            self.distances = np.linalg.norm(self.segments[:, :2], axis=1)
            self.arc = np.r_[0, np.cumsum(self.distances)]
            reply["path"] = self.path.tolist()
            return dict(reply, reason="planning_walk", remaining=float(self.arc[-1]))
        last_stop = self.stop_index == len(self.stops) - 1
        if (
            math.dist(eye[:2], self.goal[:2]) <= 0.9
            and 0.85 < eye[2] - self.goal[2] < 2.55
            and (last_stop or len(self.pavement_below(eye)) == 1)
        ):
            self.motion_origin = None
            if speed > 1.0 or self.arrival is None:
                self.arrival = now
            if now - self.arrival < 0.38:
                return dict(reply, reason="stopping", remaining=0.0)
            if last_stop:
                self.arrived = True
                return dict(reply, reason="arrived", remaining=0.0)
            self.stop_index += 1
            self.goal = self.stops[self.stop_index]
            self.arrival = self.path = self.entry = None
            self.crossings = ()
            self.last_plan = -math.inf
            return dict(reply, reason="planning_walk", path=[], stopIndex=self.stop_index)
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
        if self.motion_origin and math.dist(self.motion_origin[1], eye[:2]) >= 0.35:
            self.motion_origin = None
        stalled = 0 if self.motion_origin is None else now - self.motion_origin[0]
        if stalled >= 6:
            return dict(reply, reason="no_motion", remaining=remaining)

        def point_at(lookahead):
            return np.array([
                np.interp(min(self.arc[-1], station + lookahead), self.arc, col)
                for col in self.path.T
            ])

        def reachable(end):
            return (
                math.dist(start[:2], end[:2]) >= 0.05
                and self.surface.sweep_route(start, end, self.crossings, self.entry)
                and self.surface.step_supported(start, end)
            )

        def nearby_step(turns):
            # Small steer-around within the corridor. A floor-only sweep can
            # otherwise cut the corner of a walk polygon and hold the stick still.
            forward = point_at(0.55) - start
            angle = math.atan2(forward[1], forward[0])
            lane = projected[max(0, index - 1) : index + 2, :2]
            for turn in turns:
                bearing = angle + turn
                offset = np.array([0.5 * math.cos(bearing), 0.5 * math.sin(bearing), 0.0])
                proposed = start + offset
                if np.linalg.norm(lane - proposed[:2], axis=1).min() <= 0.65 and reachable(proposed):
                    return proposed
            return None

        recovering = stalled >= 0.9
        aim = None
        if recovering:
            # A small camera-position error can put the pose on the opposite side
            # of a nav-mesh edge. Try a different direction when motion stays flat.
            turns = (-0.65, 0.65, -0.9, 0.9)
            side = min(3, int((stalled - 0.9) / 0.9))
            aim = nearby_step(turns[side:] + turns[:side])
        if aim is None:
            preferred = (point_at(distance) for distance in (1.75, 1.05, 0.55, 0.3))
            aim = next((point for point in preferred if reachable(point)), None)
        if aim is None:
            aim = nearby_step((0.22, -0.22, 0.44, -0.44))
        if aim is None:
            return dict(reply, reason="walk_clearance_unknown", remaining=remaining)
        delta = aim - start
        error = math.remainder(math.atan2(delta[1], delta[0]) - heading, math.tau)
        if abs(error) > 0.34:
            return dict(reply, reason="walk_aligning", lookRadians=error, remaining=remaining)
        if self.motion_origin is None:
            self.motion_origin = now, eye[:2].copy()
        pace = min(0.25 if recovering else 0.35, max(0.15, 0.26 * remaining)) * (
            1 - 0.32 * abs(error)
        )
        return dict(
            reply,
            reason="walking",
            remaining=remaining,
            stick=[-pace * math.sin(error), -pace * math.cos(error)],
        )
