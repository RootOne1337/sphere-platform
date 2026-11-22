"""Single Android virtual-stick contact. Neutral moves to center, not UP/DOWN.

This pure planner sends nothing. The caller still owns native admission, exact
APPLIED receipts and final participant close. Source clock correlation is absent.
"""

from dataclasses import dataclass
from math import hypot

from motor_worker.policy import ActionChunk, GamepadState, KeyboardMouseState, finite
from motor_worker.protocol import ProtocolError, integer


@dataclass(frozen=True)
class StickGeometry:
    width: int
    height: int
    x: int
    y: int
    radius: int

    def __post_init__(self):
        if (
            not integer(self.width, 1, 4096)
            or not integer(self.height, 1, 4096)
            or not integer(self.radius, 1, 1024)
            or not integer(self.x, self.radius, self.width - 1 - self.radius)
            or not integer(self.y, self.radius, self.height - 1 - self.radius)
        ):
            raise ProtocolError("invalid_stick_geometry")


@dataclass(frozen=True)
class StickEvent:
    action: int
    x: int
    y: int
    reason: str


class VirtualStickContact:
    def __init__(
        self,
        geometry: StickGeometry,
        *,
        hold_seconds=0.35,
        max_result_age=0.4,
        max_video_age=0.25,
        rearm_seconds=0.65,
    ):
        if type(geometry) is not StickGeometry or any(
            not finite(v, low, high)
            for v, low, high in (
                (hold_seconds, 0.05, 0.5),
                (max_result_age, 0.05, 0.5),
                (max_video_age, 0.05, 0.5),
                (rearm_seconds, 0.5, 2),
            )
        ):
            raise ProtocolError("invalid_stick_budget")
        self.geometry = geometry
        self.hold_seconds, self.max_result_age = hold_seconds, max_result_age
        self.max_video_age, self.rearm_seconds = max_video_age, rearm_seconds
        self.target = (geometry.x, geometry.y)
        self.last_position = self.target
        self.last_result = self.last_frame = None
        self.valid_until = self.rearm_after = 0.0

    def observe(self, x, y, received_at, completed_at):
        """Screen axes: +x right, +y down. Model axis conversion belongs outside."""
        if (
            not finite(x, -1, 1)
            or not finite(y, -1, 1)
            or not finite(received_at, 0, float("inf"))
            or not finite(completed_at, 0, float("inf"))
            or completed_at < received_at
            or self.last_result is not None
            and completed_at <= self.last_result
            or self.last_frame is not None
            and received_at < self.last_frame
        ):
            raise ProtocolError("invalid_stick_observation")
        if completed_at - received_at > self.max_result_age:
            self.valid_until = 0
            self.last_result, self.last_frame = completed_at, received_at
            return False
        scale = max(1.0, hypot(x, y))
        g = self.geometry
        self.target = (round(g.x + g.radius * x / scale), round(g.y + g.radius * y / scale))
        self.last_result, self.last_frame = completed_at, received_at
        # Prediction age and command lifetime are separate. Expiring at
        # received_at+400ms caused a release between ~250ms GPU predictions.
        self.valid_until = completed_at + self.hold_seconds
        return True

    def next_event(self, now, video_received_at, *, held, pending=False):
        if not finite(now, 0, float("inf")) or type(held) is not bool or type(pending) is not bool:
            raise ProtocolError("invalid_stick_tick")
        if pending:
            return None  # Never queue/replay around an unknown native action.
        fresh = (
            self.last_result is not None
            and self.last_result <= now < self.valid_until
            and finite(video_received_at, 0, now)
            and now - video_received_at <= self.max_video_age
        )
        if not fresh:
            return StickEvent(1, *self.last_position, "expired_or_video_stale") if held else None
        if not held:
            return (
                StickEvent(0, self.geometry.x, self.geometry.y, "engage")
                if now >= self.rearm_after
                else None
            )
        if self.target != self.last_position:
            return StickEvent(2, *self.target, "direction_or_neutral_center")
        return None

    def sent(self, event: StickEvent, now):
        """Call after the native actor reserves a sequence, before possible partial send."""
        if (
            type(event) is not StickEvent
            or not integer(event.action, 0, 2)
            or not integer(event.x, 0, self.geometry.width - 1)
            or not integer(event.y, 0, self.geometry.height - 1)
            or not finite(now, 0, float("inf"))
        ):
            raise ProtocolError("invalid_stick_event")
        self.last_position = (event.x, event.y)
        if event.action == 1:
            self.rearm_after = now + self.rearm_seconds


class GamepadStickTrajectory:
    """Latest gamepad chunk on a real-time clock; no queue or catch-up bursts.

    Gamepad +Y points upward. Only the left stick is mapped; this is not a
    camera/button executor or goal planner. A new accepted chunk supersedes the
    old one. Late ticks select the current state rather than replaying history.
    """

    def __init__(self, geometry: StickGeometry, *, deadzone=0.15, **contact_budgets):
        if not finite(deadzone, 0, 0.5):
            raise ProtocolError("invalid_stick_deadzone")
        self.contact = VirtualStickContact(geometry, **contact_budgets)
        self.deadzone = deadzone
        self.chunk = None
        self.started_at = None
        self.last_tick = None
        self.current_index = None
        self.skipped_states = 0
        self.superseded_states = 0

    def _axes(self, state):
        x, y = state.left
        return (x, -y) if hypot(x, y) >= self.deadzone else (0, 0)

    def observe(self, chunk, received_at, completed_at):
        if (
            type(chunk) is not ActionChunk
            or not finite(completed_at, 0, float("inf"))
            or any(type(state) is not GamepadState for state in chunk.states)
            or len(chunk.states) / chunk.ticks_per_second > 0.5
            or self.last_tick is not None
            and completed_at < self.last_tick
        ):
            raise ProtocolError("invalid_stick_trajectory")
        # Validate lineage/age in the contact before mutating the active plan.
        accepted = self.contact.observe(*self._axes(chunk.states[0]), received_at, completed_at)
        if self.chunk is not None:
            previous = self.current_index if self.current_index is not None else -1
            self.superseded_states += len(self.chunk.states) - previous - 1
        self.chunk = chunk if accepted else None
        self.started_at = completed_at
        self.current_index = None
        if accepted:
            # A prediction's finite horizon is never extended by render ticks.
            self.contact.valid_until = min(
                self.contact.valid_until,
                completed_at + len(chunk.states) / chunk.ticks_per_second,
            )
        return accepted

    def next_event(self, now, video_received_at, *, held, pending=False):
        if (
            not finite(now, 0, float("inf"))
            or type(held) is not bool
            or type(pending) is not bool
            or self.last_tick is not None
            and now < self.last_tick
            or self.started_at is not None
            and now < self.started_at
        ):
            raise ProtocolError("invalid_stick_trajectory_time")
        self.last_tick = now
        if self.chunk is not None and now < self.contact.valid_until:
            index = int((now - self.started_at) * self.chunk.ticks_per_second)
            if index < len(self.chunk.states) and not pending:
                previous = self.current_index if self.current_index is not None else -1
                self.skipped_states += max(0, index - previous - 1)
                self.current_index = index
                x, y = self._axes(self.chunk.states[index])
                scale = max(1.0, hypot(x, y))
                g = self.contact.geometry
                self.contact.target = (
                    round(g.x + g.radius * x / scale),
                    round(g.y + g.radius * y / scale),
                )
        return self.contact.next_event(now, video_received_at, held=held, pending=pending)

    def sent(self, event, now):
        self.contact.sent(event, now)


class WasdStickContact:
    """Explicit WASD-only projection with the same persistent contact semantics.

    Other P2P channels fail closed unless the caller explicitly opts into masking
    them. Masking is counted and is not equivalent to complete game control.
    """

    def __init__(self, geometry: StickGeometry, *, mask_other_channels=False, **contact_budgets):
        if type(mask_other_channels) is not bool:
            raise ProtocolError("invalid_wasd_channel_mask")
        self.contact = VirtualStickContact(geometry, **contact_budgets)
        self.mask_other_channels = mask_other_channels
        self.masked_predictions = 0

    def observe(self, state, received_at, completed_at):
        if type(state) is not KeyboardMouseState:
            raise ProtocolError("invalid_wasd_state")
        other = bool(
            set(state.keys) - {"w", "a", "s", "d"}
            or state.mouse_buttons
            or state.mouse_delta_x
            or state.mouse_delta_y
        )
        if other and not self.mask_other_channels:
            raise ProtocolError("unmapped_wasd_channels")
        accepted = self.contact.observe(
            int("d" in state.keys) - int("a" in state.keys),
            int("s" in state.keys) - int("w" in state.keys),
            received_at,
            completed_at,
        )
        self.masked_predictions += other
        return accepted

    def next_event(self, now, video_received_at, *, held, pending=False):
        return self.contact.next_event(now, video_received_at, held=held, pending=pending)

    def sent(self, event, now):
        self.contact.sent(event, now)
