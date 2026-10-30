"""Finite single-finger transport check, not a game profile or model policy.

Uses the recorded path vocabulary but deliberately limits a probe to 5 seconds
and 64 points. An exact video geometry is required; there is no blind remapping.
"""

from __future__ import annotations

from dataclasses import dataclass

from motor_worker.protocol import ProtocolError, integer, message


@dataclass(frozen=True)
class ProbePoint:
    at_ms: int
    action: int
    x: int
    y: int


@dataclass(frozen=True)
class PointerProbe:
    width: int
    height: int
    points: tuple[ProbePoint, ...]

    def __post_init__(self) -> None:
        if (
            not integer(self.width, 1, 8192)
            or not integer(self.height, 1, 8192)
            or type(self.points) is not tuple
            or not 2 <= len(self.points) <= 64
        ):
            raise ProtocolError("invalid_pointer_probe")
        previous = 0
        for i, p in enumerate(self.points):
            expected = 0 if i == 0 else 1 if i == len(self.points) - 1 else 2
            if (
                type(p) is not ProbePoint
                or not integer(p.at_ms, previous, 5000)
                or i == 0
                and p.at_ms != 0
                or not integer(p.action, expected, expected)
                or not integer(p.x, 0, self.width - 1)
                or not integer(p.y, 0, self.height - 1)
            ):
                raise ProtocolError("invalid_pointer_probe")
            previous = p.at_ms

    @classmethod
    def parse(cls, raw: str) -> PointerProbe:
        d = message(raw, 16384)
        if (
            d.keys() != {"schema_version", "frame_width", "frame_height", "points"}
            or not integer(d["schema_version"], 1, 1)
            or type(d["points"]) is not list
            or not 2 <= len(d["points"]) <= 64
        ):
            raise ProtocolError("invalid_pointer_probe")
        points = []
        for p in d["points"]:
            if type(p) is not dict or p.keys() != {"t_ms", "action", "x", "y"}:
                raise ProtocolError("invalid_pointer_probe")
            points.append(ProbePoint(p["t_ms"], p["action"], p["x"], p["y"]))
        return cls(d["frame_width"], d["frame_height"], tuple(points))
