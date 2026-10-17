"""Bounded shadow inference boundary. Nothing in this module can send Android input.

The NitroGen decoded response vocabulary is pinned to upstream32608444. This is
an independent validator, not an imported model, preprocessing implementation or
gamepad executor. Times are worker monotonic receiver times, never capture times.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Callable, Protocol

from motor_worker.protocol import ProtocolError, integer

BUTTON_TOKENS = (
    "BACK",
    "DPAD_DOWN",
    "DPAD_LEFT",
    "DPAD_RIGHT",
    "DPAD_UP",
    "EAST",
    "GUIDE",
    "LEFT_SHOULDER",
    "LEFT_THUMB",
    "LEFT_TRIGGER",
    "NORTH",
    "RIGHT_BOTTOM",
    "RIGHT_LEFT",
    "RIGHT_RIGHT",
    "RIGHT_SHOULDER",
    "RIGHT_THUMB",
    "RIGHT_TRIGGER",
    "RIGHT_UP",
    "SOUTH",
    "START",
    "WEST",
)
# ng.pt (HF584c8dde) predicts 18 actions; its 16 denoising steps are unrelated.
MAX_ACTION_STATES = 18
# elefant-ai/open-p2p a329d98c, data/action_mapping.py (150M defaults).
P2P_KEYS = frozenset(
    (
        "Space",
        "1",
        "2",
        "3",
        "4",
        "a",
        "d",
        "e",
        "f",
        "q",
        "w",
        "s",
        "z",
        "DownArrow",
        "UpArrow",
        "LeftArrow",
        "RightArrow",
        "LeftShift",
        "RightShift",
    )
)


def finite(value: object, low: float, high: float) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value) and low <= value <= high
    except OverflowError:
        return False


def epoch_valid(value: object) -> bool:
    try:
        return type(value) is str and str(uuid.UUID(value)) == value and uuid.UUID(value).int != 0
    except (ValueError, AttributeError):
        return False


@dataclass(frozen=True)
class GamepadState:
    left: tuple[float, float]
    right: tuple[float, float]
    buttons: tuple[float, ...]

    def __post_init__(self) -> None:
        if (
            any(
                type(v) is not tuple or len(v) != n
                for v, n in ((self.left, 2), (self.right, 2), (self.buttons, len(BUTTON_TOKENS)))
            )
            or any(not finite(v, -1, 1) for v in (*self.left, *self.right))
            or any(not finite(v, 0, 1) or v not in (0, 1) for v in self.buttons)
        ):
            raise ProtocolError("invalid_policy_state")

    @classmethod
    def neutral(cls) -> GamepadState:
        return cls((0.0, 0.0), (0.0, 0.0), (0.0,) * len(BUTTON_TOKENS))


@dataclass(frozen=True)
class KeyboardMouseState:
    """Decoded P2P vocabulary, not Android keycodes or a physical input sink."""

    keys: tuple[str, ...]
    mouse_buttons: tuple[str, ...]
    mouse_delta_x: int
    mouse_delta_y: int

    def __post_init__(self) -> None:
        for values, allowed, limit in (
            (self.keys, P2P_KEYS, 4),
            (self.mouse_buttons, frozenset(("0", "1", "2")), 2),
        ):
            if (
                type(values) is not tuple
                or len(values) > limit
                or any(type(v) is not str or v not in allowed for v in values)
                or len(set(values)) != len(values)
            ):
                raise ProtocolError("invalid_policy_state")
        # Pinned truncated_normal decoder rounds to integer pixels. The outer
        # bins are +/-501, within this explicit envelope; never clip a reply.
        if any(not integer(v, -1024, 1024) for v in (self.mouse_delta_x, self.mouse_delta_y)):
            raise ProtocolError("invalid_policy_state")

    @classmethod
    def neutral(cls) -> KeyboardMouseState:
        return cls((), (), 0, 0)


@dataclass(frozen=True)
class ActionChunk:
    states: tuple[GamepadState | KeyboardMouseState, ...]
    ticks_per_second: float

    def __post_init__(self) -> None:
        if (
            type(self.states) is not tuple
            or not 1 <= len(self.states) <= MAX_ACTION_STATES
            or any(type(s) not in (GamepadState, KeyboardMouseState) for s in self.states)
            or any(type(s) is not type(self.states[0]) for s in self.states)
            or not finite(self.ticks_per_second, 5, 120)
            or len(self.states) / self.ticks_per_second > 2
        ):
            raise ProtocolError("invalid_policy_chunk")

    @classmethod
    def from_nitrogen(cls, prediction: object, *, ticks_per_second: float) -> ActionChunk:
        # Provider bridges must convert model arrays to bounded plain lists. No
        # pickle, raw tensor deserialization, clipping or guessed timestep here.
        if type(prediction) is not dict or prediction.keys() != {"j_left", "j_right", "buttons"}:
            raise ProtocolError("invalid_policy_prediction")
        left, right, buttons = (prediction[k] for k in ("j_left", "j_right", "buttons"))
        if (
            any(type(v) is not list for v in (left, right, buttons))
            or not 1 <= len(left) <= MAX_ACTION_STATES
            or len(left) != len(right)
            or len(left) != len(buttons)
        ):
            raise ProtocolError("invalid_policy_prediction")
        states = []
        for a, b, c in zip(left, right, buttons):
            if any(type(v) is not list for v in (a, b, c)) or (len(a), len(b), len(c)) != (
                2,
                2,
                21,
            ):
                raise ProtocolError("invalid_policy_prediction")
            states.append(GamepadState(tuple(a), tuple(b), tuple(c)))
        return cls(tuple(states), ticks_per_second)

    @classmethod
    def from_open_p2p(cls, prediction: object) -> ActionChunk:
        if (
            type(prediction) is not dict
            or prediction.keys() != {"keys", "mouse_buttons", "mouse_delta_x", "mouse_delta_y"}
            or type(prediction["keys"]) is not list
            or type(prediction["mouse_buttons"]) is not list
        ):
            raise ProtocolError("invalid_policy_prediction")
        return cls(
            (
                KeyboardMouseState(
                    tuple(prediction["keys"]),
                    tuple(prediction["mouse_buttons"]),
                    prediction["mouse_delta_x"],
                    prediction["mouse_delta_y"],
                ),
            ),
            20,
        )

    def preview_at(self, elapsed: float) -> GamepadState | KeyboardMouseState:
        """Read-only state timeline: never restart the chunk on a late callback."""
        if not finite(elapsed, 0, 60):
            raise ProtocolError("invalid_policy_time")
        index = int(elapsed * self.ticks_per_second)
        return self.states[index] if index < len(self.states) else type(self.states[0]).neutral()


@dataclass(frozen=True)
class PolicyFrame:
    capture_epoch: str
    receiver_sequence: int
    received_at: float
    width: int
    height: int
    rgb24: bytes

    def __post_init__(self) -> None:
        if (
            not epoch_valid(self.capture_epoch)
            or not integer(self.receiver_sequence, 1, 2**53 - 1)
            or not finite(self.received_at, 0, float("inf"))
            or not integer(self.width, 1, 4096)
            or not integer(self.height, 1, 4096)
            or self.width * self.height > 8 * 1024 * 1024
            or type(self.rgb24) is not bytes
            or len(self.rgb24) != self.width * self.height * 3
        ):
            raise ProtocolError("invalid_policy_frame")


@dataclass(frozen=True)
class PolicyRequest:
    request_id: int
    frame: PolicyFrame
    deadline: float


@dataclass(frozen=True)
class PolicyResult:
    request_id: int
    capture_epoch: str
    receiver_sequence: int
    chunk: ActionChunk


class Policy(Protocol):
    async def predict(self, request: PolicyRequest) -> PolicyResult: ...


class NeutralPolicy:
    """Explicit fixture for real-frame shadow plumbing, not a learned policy."""

    async def predict(self, request: PolicyRequest) -> PolicyResult:
        await asyncio.sleep(0)
        return PolicyResult(
            request.request_id,
            request.frame.capture_epoch,
            request.frame.receiver_sequence,
            ActionChunk((GamepadState.neutral(),) * 16, 60),
        )


class ShadowPolicyLoop:
    """One active inference plus one replaceable latest frame, no input sink.

    A provider must be cancellable asynchronous work (or an isolated process),
    never blocking GPU work on this event loop. A timeout does not prove CUDA work
    stopped. If the coroutine cannot retire, no new inference is launched.
    """

    def __init__(
        self,
        provider: Policy,
        *,
        timeout: float = 0.25,
        max_receiver_age: float = 0.5,
        clock: Callable[[], float] = time.perf_counter,
    ):
        if not finite(timeout, 0.01, 2) or not finite(max_receiver_age, 0.01, 2):
            raise ProtocolError("invalid_policy_budget")
        self.provider, self.timeout, self.max_receiver_age, self.clock = (
            provider,
            timeout,
            max_receiver_age,
            clock,
        )
        self.epoch: str | None = None
        self.generation = 0
        self.active_generation = 0
        self.last_sequence = 0
        self.pending: PolicyFrame | None = None
        self.request: PolicyRequest | None = None
        self.task: asyncio.Task | None = None
        self.last_chunk: ActionChunk | None = None
        self.last_chunk_deadline = 0.0
        self.closed = False
        self.offered = self.submitted = self.accepted = self.replaced = 0
        self.stale_frames = self.expired_results = self.foreign_results = self.timed_out = 0
        self.last_started_at = 0.0
        self.samples: deque[dict] = deque(maxlen=64)

    def bind_epoch(self, epoch: str) -> None:
        if self.closed or not epoch_valid(epoch):
            raise ProtocolError("invalid_policy_epoch")
        if self.epoch != epoch:
            self.generation += 1
            self.epoch, self.last_sequence, self.pending, self.last_chunk = epoch, 0, None, None

    def offer(self, frame: PolicyFrame) -> None:
        if self.closed or type(frame) is not PolicyFrame or frame.capture_epoch != self.epoch:
            raise ProtocolError("policy_frame_binding_mismatch")
        if frame.receiver_sequence <= self.last_sequence:
            raise ProtocolError("policy_frame_sequence_reused")
        self.last_sequence = frame.receiver_sequence
        self.offered += 1
        if not 0 <= self.clock() - frame.received_at <= self.max_receiver_age:
            self.stale_frames += 1
            return
        if self.pending is not None:
            self.replaced += 1
        self.pending = frame

    async def _cancel_active(self) -> None:
        if self.task is None:
            return
        self.task.cancel()
        done, _ = await asyncio.wait({self.task}, timeout=0.1)
        if not done:
            self.closed, self.pending, self.last_chunk = True, None, None
            raise ProtocolError("policy_cleanup_unconfirmed")
        # Consume all outcomes without exposing provider exception text.
        try:
            self.task.result()
        except (Exception, asyncio.CancelledError):
            pass
        self.task = self.request = None

    async def tick(self) -> None:
        if self.closed:
            return
        now = self.clock()
        if now >= self.last_chunk_deadline:
            self.last_chunk = None
        if self.task is not None:
            if self.task.done():
                try:
                    result = self.task.result()
                except (Exception, asyncio.CancelledError) as exc:
                    self.task = self.request = None
                    self.last_chunk = None
                    self.closed = True
                    raise ProtocolError("policy_inference_failed") from exc
                req = self.request
                self.task = self.request = None
                if not req.frame.received_at <= now < req.deadline:
                    self.expired_results += 1
                    self.last_chunk = None
                elif (
                    req.frame.capture_epoch != self.epoch
                    or self.active_generation != self.generation
                ):
                    self.foreign_results += 1
                    self.last_chunk = None
                elif (
                    type(result) is not PolicyResult
                    or type(result.request_id) is not int
                    or result.request_id != req.request_id
                    or type(result.receiver_sequence) is not int
                    or result.receiver_sequence != req.frame.receiver_sequence
                    or result.capture_epoch != req.frame.capture_epoch
                    or type(result.chunk) is not ActionChunk
                ):
                    self.last_chunk = None
                    self.closed = True
                    raise ProtocolError("policy_result_binding_mismatch")
                else:
                    self.accepted += 1
                    self.last_chunk = result.chunk
                    self.last_chunk_deadline = req.deadline
                    self.samples.append(
                        {
                            "requestId": req.request_id,
                            "receiverSequence": req.frame.receiver_sequence,
                            "receiverAgeAtResultMs": round((now - req.frame.received_at) * 1000, 3),
                            "inferenceWallMs": round((now - self.last_started_at) * 1000, 3),
                            "chunkStates": len(result.chunk.states),
                            "chunkTicksPerSecond": result.chunk.ticks_per_second,
                        }
                    )
            elif now >= self.request.deadline:
                self.timed_out += 1
                self.last_chunk = None
                await self._cancel_active()
                now = self.clock()
        if self.task is None and self.pending is not None:
            frame, self.pending = self.pending, None
            if not 0 <= now - frame.received_at < self.max_receiver_age:
                self.stale_frames += 1
                return
            self.submitted += 1
            self.active_generation = self.generation
            self.last_started_at = now
            self.request = PolicyRequest(
                self.submitted,
                frame,
                min(now + self.timeout, frame.received_at + self.max_receiver_age),
            )
            self.task = asyncio.create_task(self.provider.predict(self.request))

    async def close(self) -> None:
        self.closed, self.pending, self.last_chunk = True, None, None
        await self._cancel_active()

    def report(self) -> dict:
        return {
            "enabled": True,
            "kind": "neutral_fixture_shadow_not_model_inference"
            if type(self.provider) is NeutralPolicy
            else "external_provider_shadow_not_gameplay",
            "physicalActionsSent": 0,
            "offered": self.offered,
            "submitted": self.submitted,
            "accepted": self.accepted,
            "replacedPending": self.replaced,
            "staleFramesDropped": self.stale_frames,
            "expiredResultsDropped": self.expired_results,
            "foreignEpochResultsDropped": self.foreign_results,
            "timedOut": self.timed_out,
            "activeRequestSlots": 1,
            "pendingFrameSlots": 1,
            "sampleTailLimit": 64,
            "cleanupConfirmed": self.closed and self.task is None and self.pending is None,
            "inputTransform": "original_rgb24_no_model_preprocessing",
            "freshnessClock": "worker_receiver_not_source_capture",
            "samples": list(self.samples),
        }
