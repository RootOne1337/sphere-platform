"""Analog walking intent from a calibrated local heading, with no input sink.

The caller supplies collision clearance and camera-relative route geometry.
This is neither a detector nor a vehicle controller. Unknown or blocked space
stops immediately; speed ramps never delay a safety stop.
"""

import math
from dataclasses import dataclass

from motor_worker.policy import finite
from motor_worker.protocol import ProtocolError


@dataclass(frozen=True)
class WalkingIntent:
    x: float
    y: float
    reason: str


class WalkingSteering:
    def __init__(self, *, max_deflection=0.8, min_deflection=0.25, acceleration=1.0):
        if (
            not finite(max_deflection, 0.1, 1)
            or not finite(min_deflection, 0.05, max_deflection)
            or not finite(acceleration, 0.1, 5)
        ):
            raise ProtocolError("invalid_walking_steering_budget")
        self.maximum, self.minimum = max_deflection, min_deflection
        self.acceleration = acceleration
        self.last_now = None
        self.speed = 0.0

    def observe(self, heading_degrees, *, clearance, received_at, now, speed_cap=1.0):
        if (
            heading_degrees is not None
            and not finite(heading_degrees, -180, 180)
            or type(clearance) is not str
            or clearance not in {"clear", "caution", "blocked", "unknown"}
            or not finite(now, 0, float("inf"))
            or not finite(received_at, 0, now)
            or self.last_now is not None
            and now <= self.last_now
            or not finite(speed_cap, 0, 1)
        ):
            raise ProtocolError("invalid_walking_steering_observation")
        elapsed = 0 if self.last_now is None else now - self.last_now
        self.last_now = now
        if now - received_at > 0.25 or elapsed > 0.5:
            reason = "observation_stale_or_gap"
        elif clearance in {"blocked", "unknown"}:
            reason = "clearance_" + clearance
        elif heading_degrees is None:
            reason = "route_direction_unknown"
        elif speed_cap == 0:
            reason = "speed_cap_zero"
        else:
            # Sharp corrections are walked slowly instead of applying full
            # stick travel while the game's camera is still recentering.
            bend = min(1.0, abs(heading_degrees) / 90)
            target = min(self.maximum - (self.maximum - self.minimum) * bend, speed_cap)
            if clearance == "caution":
                target = min(target, self.minimum)
            self.speed = min(target, self.speed + self.acceleration * elapsed)
            angle = math.radians(heading_degrees)
            return WalkingIntent(self.speed * math.sin(angle), -self.speed * math.cos(angle), "follow")
        self.speed = 0.0
        return WalkingIntent(0.0, 0.0, reason)
