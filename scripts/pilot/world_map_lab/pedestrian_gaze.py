"""Coordinate pedestrian movement and first-person camera corrections in map radians."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WalkIntent:
    turn: float
    forward: float
    right: float


def face_travel(bearing: float, heading: float, elapsed: float) -> WalkIntent:
    angle = math.remainder(bearing - heading, 2 * math.pi)
    limit = math.radians(55) * max(0.0, min(elapsed, 0.2))
    turn = max(-limit, min(limit, angle)) if abs(angle) > math.radians(4) else 0.0
    # Correct the view while stationary before committing to a different street.
    speed = max(0.0, min(1.0, (math.radians(36) - abs(angle)) / math.radians(21)))
    # Use the camera for a turn. Keep sideways stick corrections small even
    # when the next waypoint is already on the other side of a corner.
    trim = max(-math.radians(8), min(math.radians(8), angle))
    return WalkIntent(turn, speed * math.cos(trim), -speed * math.sin(trim))
