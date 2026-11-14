"""Finite sequential gestures with exact native receipts owned by the caller.

This permits release/camera-drag/release or two taps, never simultaneous fingers.
Reservation is at most once. Unknown delivery must close the participant, not
rewind/retry this sequence. Geometry and UI calibration belong to the profile.
"""

from dataclasses import dataclass

from motor_worker.pointer_probe import ProbePoint
from motor_worker.policy import finite
from motor_worker.protocol import ProtocolError, integer


@dataclass(frozen=True)
class PointerSequence:
    width: int
    height: int
    points: tuple[ProbePoint, ...]

    def __post_init__(self):
        if (
            not integer(self.width, 1, 4096)
            or not integer(self.height, 1, 4096)
            or type(self.points) is not tuple
            or not 2 <= len(self.points) <= 64
        ):
            raise ProtocolError("invalid_pointer_sequence")
        held, previous = False, -1
        for index, point in enumerate(self.points):
            if (
                type(point) is not ProbePoint
                or not integer(point.at_ms, previous + 1, 5000)
                or index == 0
                and point.at_ms != 0
                or not integer(point.action, 0, 2)
                or not integer(point.x, 0, self.width - 1)
                or not integer(point.y, 0, self.height - 1)
                or (held if point.action == 0 else not held)
            ):
                raise ProtocolError("invalid_pointer_sequence")
            held = point.action != 1
            previous = point.at_ms
        if held:
            raise ProtocolError("pointer_sequence_release_required")

    @classmethod
    def double_tap(cls, width, height, x, y):
        return cls(
            width,
            height,
            tuple(
                ProbePoint(t, action, x, y) for t, action in ((0, 0), (60, 1), (180, 0), (240, 1))
            ),
        )

    @classmethod
    def camera_drag(cls, width, height, start, end):
        if (
            type(start) is not tuple
            or type(end) is not tuple
            or len(start) != 2
            or len(end) != 2
            or any(not integer(v, 0, 4095) for v in (*start, *end))
        ):
            raise ProtocolError("invalid_pointer_sequence")
        points = [ProbePoint(0, 0, *start)]
        for step in range(1, 7):
            x = round(start[0] + (end[0] - start[0]) * step / 6)
            y = round(start[1] + (end[1] - start[1]) * step / 6)
            points.append(ProbePoint(step * 50, 2, x, y))
        points.append(ProbePoint(320, 1, *end))
        return cls(width, height, tuple(points))


class PointerSequenceClock:
    def __init__(self, plan: PointerSequence, *, max_lateness=0.15):
        if type(plan) is not PointerSequence or not finite(max_lateness, 0.05, 0.25):
            raise ProtocolError("invalid_pointer_sequence_clock")
        self.plan, self.max_lateness = plan, max_lateness
        self.index = 0
        self.started_at = None
        self.last_now = None

    def reserve(self, now, *, held, pending, frame_age):
        if (
            not finite(now, 0, float("inf"))
            or type(held) is not bool
            or type(pending) is not bool
            or self.last_now is not None
            and now < self.last_now
        ):
            raise ProtocolError("invalid_pointer_sequence_time")
        self.last_now = now
        if not finite(frame_age, 0, 0.25):
            raise ProtocolError("pointer_sequence_frame_stale")
        if self.index == len(self.plan.points) or pending:
            return None
        if self.started_at is None:
            self.started_at = now
        point = self.plan.points[self.index]
        due = self.started_at + point.at_ms / 1000
        if now < due:
            return None
        if now - due > self.max_lateness:
            raise ProtocolError("pointer_sequence_deadline")
        if held if point.action == 0 else not held:
            raise ProtocolError("pointer_sequence_native_state_mismatch")
        self.index += 1  # Reserve before any potentially partial native send.
        return point
