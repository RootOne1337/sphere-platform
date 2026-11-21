"""Bounded recovery supervision, not an obstacle detector or game input sink.

Scene, obstacle and free-side assessments must come from a calibrated perception
adapter or operator. Unknown geometry never authorizes a jump or blind detour.
"""

from collections import deque
from dataclasses import dataclass

from motor_worker.policy import epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer


@dataclass(frozen=True)
class NavigationObservation:
    epoch: str
    sequence: int
    received_at: float
    now: float
    scene: str
    control_ready: bool
    moving: bool
    target_visible: bool
    distance_m: float | None = None
    background_motion_px: float | None = None
    low_obstacle: bool = False
    free_side: str | None = None

    def __post_init__(self):
        if (
            not epoch_valid(self.epoch)
            or not integer(self.sequence, 1, 2**53 - 1)
            or not finite(self.now, 0, float("inf"))
            or not finite(self.received_at, 0, self.now)
            or type(self.scene) is not str
            or self.scene not in {"active", "fallen", "menu", "disconnected", "unknown"}
            or any(
                type(v) is not bool
                for v in (self.control_ready, self.moving, self.target_visible, self.low_obstacle)
            )
            or self.distance_m is not None
            and not finite(self.distance_m, 0, 100000)
            or self.background_motion_px is not None
            and not finite(self.background_motion_px, 0, 1000)
            or self.free_side is not None
            and type(self.free_side) is not str
            or self.free_side not in {None, "left", "right"}
        ):
            raise ProtocolError("invalid_navigation_observation")


@dataclass(frozen=True)
class RecoveryDirective:
    action: str
    reason: str
    operation_id: int | None = None
    side: str | None = None


class NavigationSupervisor:
    def __init__(self, *, jump_calibrated=False, stall_seconds=3.0, max_recoveries=3):
        if (
            type(jump_calibrated) is not bool
            or not finite(stall_seconds, 2, 10)
            or not integer(max_recoveries, 1, 4)
        ):
            raise ProtocolError("invalid_navigation_budget")
        self.jump_calibrated = jump_calibrated
        self.stall_seconds, self.max_recoveries = stall_seconds, max_recoveries
        self.epoch = None
        self.last_sequence = 0
        self.last_now = None
        self.samples = deque(maxlen=256)
        self.pending = None
        self.recoveries = 0
        self.next_id = 0
        self.last_recovery = None
        self.terminal_reason = None
        self.fallen_at = None
        self.jump_used = False
        self.last_received_at = None

    def _stop(self, reason, terminal=False):
        self.samples.clear()
        # An issued recovery may still be running on Android. Losing its
        # acknowledgement must never silently return this supervisor to follow.
        terminal = terminal or self.pending is not None
        self.pending = None
        if terminal:
            self.terminal_reason = reason
        return RecoveryDirective("stop", reason)

    def observe(self, observation):
        if type(observation) is not NavigationObservation:
            raise ProtocolError("invalid_navigation_observation")
        o = observation
        if o.sequence <= self.last_sequence or self.last_now is not None and o.now < self.last_now:
            return self._stop("observation_order", terminal=True)
        if self.last_received_at is not None and o.received_at <= self.last_received_at:
            return self._stop("observation_clock_order", terminal=True)
        gap = self.last_received_at is not None and o.received_at - self.last_received_at > 0.5
        self.last_sequence, self.last_now = o.sequence, o.now
        self.last_received_at = o.received_at
        if self.terminal_reason:
            return RecoveryDirective("stop", self.terminal_reason)
        if self.epoch is None:
            self.epoch = o.epoch
        if o.epoch != self.epoch:
            return self._stop("capture_epoch_changed", terminal=True)
        if o.now - o.received_at > 0.25:
            return self._stop("receiver_frame_stale")
        # A new fresh frame after a long blind interval is not evidence of
        # continuous progress or a continuously stalled character. Stop first;
        # collecting a new progress window must not erase an in-flight action.
        if gap:
            if self.pending:
                return self._stop("recovery_observation_gap", terminal=True)
            return self._stop("progress_observation_gap")
        if not o.control_ready:
            return self._stop("native_control_not_ready")
        if o.scene == "disconnected":
            return self._stop("game_disconnected", terminal=True)
        if o.scene in {"menu", "unknown"}:
            return self._stop("game_scene_not_active")
        if o.scene == "fallen":
            if self.pending:
                return self._stop("recovery_interrupted_unconfirmed", terminal=True)
            self.samples.clear()
            if self.fallen_at is None:
                self.fallen_at = o.now
            if o.now - self.fallen_at > 6:
                return self._stop("fall_recovery_unconfirmed", terminal=True)
            return RecoveryDirective("wait", "wait_for_standing")
        if self.fallen_at is not None:
            self.fallen_at = None
            self.samples.clear()
        if not o.target_visible:
            return self._stop("target_missing_not_arrival")
        if self.pending:
            if o.now > self.pending[1]:
                return self._stop("recovery_receipt_unknown", terminal=True)
            return RecoveryDirective("wait", "recovery_in_flight", self.pending[0])
        if not o.moving:
            self.samples.clear()
            return RecoveryDirective("follow", "idle_progress_window_reset")
        self.samples.append(o)
        # Keep one boundary sample; this is bounded history, not a command queue.
        while len(self.samples) > 1 and self.samples[1].now <= o.now - self.stall_seconds:
            self.samples.popleft()
        first = self.samples[0]
        if o.now - first.now < self.stall_seconds:
            return RecoveryDirective("follow", "collecting_progress")
        if first.distance_m is not None and o.distance_m is not None:
            stalled = first.distance_m - o.distance_m < 0.5
        else:
            motion = [s.background_motion_px for s in self.samples]
            if any(v is None for v in motion):
                return self._stop("progress_evidence_missing")
            # One animation/feature-tracking outlier must not renew a whole
            # three-second movement window. Weight intervals, not frame count;
            # camera motion can still make this sensor inconclusive.
            quiet_seconds = sum(
                b.now - a.now
                for a, b in zip(self.samples, list(self.samples)[1:])
                if b.background_motion_px < 0.35
            )
            stalled = quiet_seconds / (o.now - first.now) >= 0.85
        if not stalled:
            if first.distance_m is None or o.distance_m is None:
                # Screen motion can be camera rotation, animation, or traffic.
                # It disproves the narrow still-image stall heuristic but does
                # not establish progress toward the destination.
                return self._stop("goal_progress_unconfirmed", terminal=True)
            self.samples.clear()
            self.samples.append(o)
            return RecoveryDirective("follow", "goal_progress_observed")
        self.samples.clear()
        if self.recoveries >= self.max_recoveries:
            return self._stop("recovery_budget_exhausted", terminal=True)
        if self.last_recovery is None:
            action, side = "inspect_camera", None
        elif o.low_obstacle and self.jump_calibrated and not self.jump_used:
            action, side = "jump_double_tap", None
            self.jump_used = True
        elif o.free_side:
            action, side = "detour", o.free_side
        else:
            return self._stop("free_path_unknown", terminal=True)
        self.recoveries += 1
        self.next_id += 1
        self.pending = (self.next_id, o.now + 4, action)
        return RecoveryDirective(action, "goal_progress_stalled", self.next_id, side)

    def complete_recovery(self, operation_id, *, confirmed, now):
        if (
            type(confirmed) is not bool
            or not finite(now, 0, float("inf"))
            or not integer(operation_id, 1, 2**31 - 1)
            or not self.pending
            or operation_id != self.pending[0]
            or self.last_now is not None
            and now < self.last_now
        ):
            raise ProtocolError("invalid_recovery_confirmation")
        if not confirmed or now > self.pending[1]:
            self._stop("recovery_receipt_unknown", terminal=True)
            return
        self.last_recovery = self.pending[2]
        self.pending = None
        self.samples.clear()
        self.last_now = now


def background_motion(previous_rgb, current_rgb):
    """Optional OpenCV sensor: exclude HUD, touch controls and central avatar.

    Returns median feature displacement in original-frame pixels, or None for
    insufficient evidence. Camera movement is not semantic goal progress.
    """
    import cv2
    import numpy as np

    if (
        type(previous_rgb) is not np.ndarray
        or type(current_rgb) is not np.ndarray
        or previous_rgb.shape != current_rgb.shape
        or previous_rgb.dtype != np.uint8
        or current_rgb.dtype != np.uint8
        or previous_rgb.shape != (540, 960, 3)
    ):
        raise ProtocolError("invalid_motion_frame")
    before = cv2.cvtColor(previous_rgb, cv2.COLOR_RGB2GRAY)
    after = cv2.cvtColor(current_rgb, cv2.COLOR_RGB2GRAY)
    mask = np.zeros(before.shape, dtype=np.uint8)
    mask[160:420, 180:800] = 255
    mask[180:540, 350:620] = 0
    # Select per background cell: a handful of bright fence corners otherwise
    # suppress every usable low-contrast grass/tree feature in the whole frame.
    groups = []
    for top in (160, 290):
        for left in (180, 335, 490, 645):
            cell = before[top : top + 130, left : left + 155]
            selected = cv2.goodFeaturesToTrack(
                cell, maxCorners=12, qualityLevel=0.01, minDistance=9,
                mask=mask[top : top + 130, left : left + 155],
            )
            if selected is not None:
                groups.append(selected + np.float32([left, top]))
    if not groups:
        return None
    points = np.concatenate(groups)
    if len(points) < 12:
        return None
    next_points, status, _ = cv2.calcOpticalFlowPyrLK(before, after, points, None)
    if next_points is None or status is None:
        return None
    returned, reverse_status, _ = cv2.calcOpticalFlowPyrLK(after, before, next_points, None)
    if returned is None or reverse_status is None:
        return None
    valid = (
        (status.reshape(-1) == 1)
        & (reverse_status.reshape(-1) == 1)
        & np.isfinite(next_points).all(axis=(1, 2))
        & (np.linalg.norm((returned - points).reshape(-1, 2), axis=1) <= 1.0)
    )
    if int(valid.sum()) < 12:
        return None
    # Do not call one animated local patch world movement. Require features
    # spread across at least three background cells, with the avatar excluded.
    original = points.reshape(-1, 2)[valid]
    cells = {(int(x) // 160, int(y) // 130) for x, y in original}
    if len(cells) < 3:
        return None
    shift = np.linalg.norm((next_points - points).reshape(-1, 2)[valid], axis=1)
    return float(np.median(shift))
