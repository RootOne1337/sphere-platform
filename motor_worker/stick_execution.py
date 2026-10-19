"""Explicit model-to-stick execution; no game detection or goal planning.

A calibrated caller supplies the scene guard. Camera/buttons remain unmapped;
masking them is an explicit, reported experiment rather than full game control.
"""

import asyncio
import math
import time
from collections import deque
from dataclasses import dataclass

from motor_worker.policy import ActionChunk, GamepadState, KeyboardMouseState, PolicyFrame, finite
from motor_worker.protocol import ProtocolError, integer
from motor_worker.session import HeadlessSession, SessionConfig
from motor_worker.virtual_stick import GamepadStickTrajectory, StickGeometry


@dataclass(frozen=True)
class StickProfile:
    geometry: StickGeometry
    source: str
    mask_other_channels: bool = False

    def __post_init__(self):
        if (
            type(self.geometry) is not StickGeometry
            or type(self.source) is not str
            or self.source not in {"gamepad_left", "wasd"}
            or type(self.mask_other_channels) is not bool
        ):
            raise ProtocolError("invalid_stick_profile")


class StickExecution:
    """Pure latest-plan planner. Native ACKs and participant cleanup belong to the session."""

    def __init__(self, profile: StickProfile):
        if type(profile) is not StickProfile:
            raise ProtocolError("invalid_stick_profile")
        self.profile = profile
        self.trajectory = GamepadStickTrajectory(profile.geometry)
        self.epoch = None
        self.scene_sequence = self.result_sequence = self.request_id = 0
        self.active_floor = 0
        self.scene_active = False
        self.scene_at = None
        self.accepted = self.rejected = self.masked = 0

    def _frame(self, frame):
        g = self.profile.geometry
        if type(frame) is not PolicyFrame or (frame.width, frame.height) != (g.width, g.height):
            raise ProtocolError("stick_frame_geometry_mismatch")
        if self.epoch is not None and frame.capture_epoch != self.epoch:
            raise ProtocolError("stick_capture_epoch_changed")
        self.epoch = frame.capture_epoch

    def pause(self):
        self.trajectory.chunk = None
        self.trajectory.contact.valid_until = 0

    def scene(self, frame: PolicyFrame, active: bool, now: float):
        self._frame(frame)
        if (
            type(active) is not bool
            or not finite(now, frame.received_at, float("inf"))
            or frame.receiver_sequence <= self.scene_sequence
            or self.scene_at is not None
            and now < self.scene_at
        ):
            raise ProtocolError("invalid_stick_scene_observation")
        self.scene_sequence, self.scene_at = frame.receiver_sequence, now
        active = active and now - frame.received_at <= 0.25
        if active and not self.scene_active:
            self.active_floor = frame.receiver_sequence
        self.scene_active = active
        if not active:
            self.pause()

    def accept(self, request_id: int, frame: PolicyFrame, chunk: ActionChunk, now: float):
        self._frame(frame)
        if (
            not integer(request_id, self.request_id + 1, 2**53 - 1)
            or frame.receiver_sequence <= self.result_sequence
            or frame.receiver_sequence > self.scene_sequence
            or not finite(now, frame.received_at, float("inf"))
            or self.scene_at is not None
            and now < self.scene_at
            or type(chunk) is not ActionChunk
        ):
            raise ProtocolError("invalid_stick_policy_lineage")
        self.request_id, self.result_sequence = request_id, frame.receiver_sequence
        if (
            not self.scene_active
            or frame.receiver_sequence < self.active_floor
            or now - frame.received_at > 0.4
            or now - self.scene_at > 0.3
        ):
            self.rejected += 1
            self.pause()
            return False
        masked = False
        if self.profile.source == "gamepad_left":
            if any(type(s) is not GamepadState for s in chunk.states):
                raise ProtocolError("stick_policy_type_mismatch")
            masked = any(math.hypot(*s.right) > 0 or any(s.buttons) for s in chunk.states)
            mapped = chunk
        else:
            if len(chunk.states) != 1 or type(chunk.states[0]) is not KeyboardMouseState:
                raise ProtocolError("stick_policy_type_mismatch")
            state = chunk.states[0]
            masked = bool(
                set(state.keys) - {"w", "a", "s", "d"}
                or state.mouse_buttons
                or state.mouse_delta_x
                or state.mouse_delta_y
            )
            # Explicit zero-order hold of the latest decoded WASD state. This
            # does not claim that P2P predicted a 350ms future action sequence.
            converted = GamepadState(
                (
                    int("d" in state.keys) - int("a" in state.keys),
                    int("w" in state.keys) - int("s" in state.keys),
                ),
                (0, 0),
                GamepadState.neutral().buttons,
            )
            mapped = ActionChunk((converted,) * 7, 20)
        if masked and not self.profile.mask_other_channels:
            self.pause()
            raise ProtocolError("unmapped_stick_channels")
        self.masked += int(masked)
        accepted = self.trajectory.observe(mapped, frame.received_at, now)
        self.accepted += int(accepted)
        return accepted

    def next_event(self, now, video_received_at, *, held, pending):
        if not finite(now, 0, float("inf")):
            raise ProtocolError("invalid_stick_tick")
        if not self.scene_active or self.scene_at is None or not 0 <= now - self.scene_at <= 0.3:
            self.pause()
        return self.trajectory.next_event(now, video_received_at, held=held, pending=pending)


class StickPolicySession(HeadlessSession):
    """Finite opt-in learned stick path on the same authenticated video/control peer.

    The provider must be asynchronous or isolated. The scene guard must identify
    the calibrated playable screen; a ready video or model output is insufficient.
    """

    def __init__(self, config: SessionConfig, *, profile, policy, scene_guard, execution_enabled):
        if (
            type(execution_enabled) is not bool
            or not execution_enabled
            or not config.probe_control
            or not config.shadow_policy
            or config.pointer_probe is not None
            or config.observation_hz < 4
            or not callable(scene_guard)
            or policy is None
        ):
            raise ProtocolError("explicit_stick_execution_required")
        super().__init__(config, policy=policy, policy_timeout=0.4, policy_max_receiver_age=0.4)
        self.execution = StickExecution(profile)
        self.scene_guard = scene_guard
        self.scene_checks = self.scene_refusals = self.consumed_results = 0
        self.execution_events = deque(maxlen=64)
        self.physical_events = 0

    def _pointer_enabled(self):
        return True

    async def _observe(self):
        period = 1 / self.config.observation_hz
        next_scene = next_policy = time.perf_counter()
        while not self.closing:
            now = time.perf_counter()
            policy_due = now >= next_policy and self.shadow.task is None
            due = now >= next_scene or policy_due
            item = self.frames.take(now, max_age=0.25) if due and self.binding else None
            if item:
                pixels = await asyncio.to_thread(
                    lambda: item.frame.to_ndarray(format="rgb24").tobytes()
                )
                frame = PolicyFrame(
                    self.binding.epoch,
                    item.receiver_sequence,
                    item.received_at,
                    item.frame.width,
                    item.frame.height,
                    pixels,
                )
                active = self.scene_guard(frame)
                self.execution.scene(frame, active, time.perf_counter())
                self.scene_checks += 1
                self.scene_refusals += int(not active)
                if active and policy_due:
                    if self.shadow.epoch is None:
                        self.shadow.bind_epoch(self.binding.epoch)
                    self.shadow.offer(frame)
                if policy_due:
                    next_policy = time.perf_counter() + period
                next_scene = time.perf_counter() + period
                self.sample_count += 1
                self.samples.append(
                    {
                        "receiverSequence": item.receiver_sequence,
                        "decodedAgeAtSelectionMs": (now - item.received_at) * 1000,
                    }
                )
            # An overdue inference selects fresh pixels as soon as its slot is
            # free. Rounding 201ms inference up to two 200ms scene ticks caused
            # a 400ms result gap and released the stick. Scene checks retain
            # their own deadline while the GPU is busy; no queued old frames or
            # catch-up requests are needed.
            await asyncio.sleep(0.005)

    def _tick_pointer_probe(self, now):
        if not self.availability or self.availability.state != "manual":
            self.execution.pause()
            return
        if self.shadow.accepted != self.consumed_results:
            self.consumed_results = self.shadow.accepted
            accepted = self.shadow.last_accepted
            if accepted:
                request, chunk = accepted
                self.execution.accept(request.request_id, request.frame, chunk, now)
        control, frame = self.admission, self.frames.latest
        event = self.execution.next_event(
            now,
            frame.received_at if frame else None,
            held=control.held,
            pending=control.pending is not None,
        )
        if event is None:
            return
        if self.physical_events >= 6000:
            raise ProtocolError("stick_native_event_budget")
        packet = control.pointer(event.action, event.x, event.y, now)
        self.execution.trajectory.sent(event, now)
        self.physical_events += 1
        self.execution_events.append(
            {"sequence": packet["sequence"], "action": event.action, "reason": event.reason}
        )
        self._send_control(packet)

    def _probe_complete(self):
        return bool(
            self.execution.accepted
            and self.physical_events
            and self.admission
            and self.admission.pending_event is None
            and self.admission.applied_receipts == self.physical_events
        )

    def report(self):
        report = super().report()
        report["kind"] = "FINITE_MODEL_STICK_EXECUTION_NOT_GOAL_NAVIGATION"
        report["policyShadow"].update(
            kind="external_provider_with_explicit_stick_execution",
            physicalActionsSent=self.physical_events,
        )
        report["stickExecution"] = {
            "enabled": True,
            "source": self.execution.profile.source,
            "maskOtherChannels": self.execution.profile.mask_other_channels,
            "maskedResults": self.execution.masked,
            "acceptedResults": self.execution.accepted,
            "rejectedResults": self.execution.rejected,
            "sceneChecks": self.scene_checks,
            "sceneRefusals": self.scene_refusals,
            "physicalEvents": self.physical_events,
            "nativeApplied": self.admission.applied_receipts if self.admission else 0,
            "eventTail": list(self.execution_events),
            "eventTailLimit": 64,
            "buttonsAndCameraImplemented": False,
            "sourceCaptureAgeMeasured": False,
            "wasdHoldMs": 350 if self.execution.profile.source == "wasd" else None,
        }
        return report
