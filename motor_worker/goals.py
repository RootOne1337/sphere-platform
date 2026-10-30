"""Goal-bound policy admission, without planning, model loading or Android input.

A provider must implement the requested conditioning. Metadata or an image overlay
cannot turn an image-only motor model into a goal-conditioned one. Changing or
clearing the goal invalidates an outstanding reply without starting another job.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

from motor_worker.policy import (
    ActionChunk,
    PolicyFrame,
    PolicyRequest,
    PolicyResult,
    epoch_valid,
    finite,
)
from motor_worker.protocol import ProtocolError, integer

KINDS = frozenset(("text", "image_point"))


@dataclass(frozen=True)
class Goal:
    task_id: str
    revision: str
    profile_revision: str
    capture_epoch: str
    expires_at: float
    kind: str
    text: str | None = None
    point: tuple[float, float] | None = None

    def __post_init__(self):
        if (
            not all(epoch_valid(v) for v in (
                self.task_id, self.revision, self.profile_revision, self.capture_epoch
            ))
            or not finite(self.expires_at, 0, float("inf"))
            or type(self.kind) is not str
            or self.kind not in KINDS
        ):
            raise ProtocolError("invalid_policy_goal")
        if self.kind == "text":
            valid = (
                type(self.text) is str
                and bool(self.text.strip())
                and len(self.text) <= 2048
                and not any(ord(c) < 32 for c in self.text)
                and self.point is None
            )
        else:
            valid = (
                self.text is None
                and type(self.point) is tuple
                and len(self.point) == 2
                and all(finite(v, 0, 1) for v in self.point)
            )
        if not valid:
            raise ProtocolError("invalid_policy_goal")


@dataclass(frozen=True)
class GoalCapabilities:
    """Adapter contract, not an attestation of the learned navigation quality."""

    kinds: frozenset[str]

    def __post_init__(self):
        if type(self.kinds) is not frozenset or not self.kinds <= KINDS:
            raise ProtocolError("invalid_goal_capabilities")


@dataclass(frozen=True)
class GoalRequest:
    observation: PolicyRequest
    goal: Goal


@dataclass(frozen=True)
class GoalResult:
    observation: PolicyResult
    goal: Goal


class GoalProvider(Protocol):
    capabilities: GoalCapabilities

    async def predict_goal(self, request: GoalRequest) -> GoalResult: ...


class GoalBoundPolicy:
    """Opt-in Policy adapter; only matching, live goals can return an action chunk.

    Provider retirement/deadlines and physical stop remain the executor's jobs.
    This gate does not spawn/cancel jobs or retry an unknown inference. One active
    request is allowed; a new goal may invalidate it but cannot overlap another.
    """

    def __init__(self, provider: GoalProvider, *, clock: Callable[[], float] = time.perf_counter):
        if (
            not isinstance(getattr(provider, "capabilities", None), GoalCapabilities)
            or not callable(getattr(provider, "predict_goal", None))
            or not callable(clock)
        ):
            raise ProtocolError("goal_provider_required")
        self.provider = provider
        self.clock = clock
        self.goal: Goal | None = None
        self.generation = 0
        self.active = False

    def set_goal(self, goal: Goal | None):
        previous = self.goal
        # Any attempted replacement invalidates the old work, including a bad or
        # unsupported new target. Never silently continue toward the old goal.
        self.generation += 1
        self.goal = None
        if goal is not None:
            if type(goal) is not Goal:
                raise ProtocolError("invalid_policy_goal")
            if goal.kind not in self.provider.capabilities.kinds:
                raise ProtocolError("unsupported_goal_conditioning")
            if goal.expires_at <= self.clock():
                raise ProtocolError("expired_policy_goal")
            if previous and goal.revision == previous.revision and goal != previous:
                raise ProtocolError("goal_revision_reused")
        self.goal = goal

    async def predict(self, request: PolicyRequest) -> PolicyResult:
        now = self.clock()
        if self.active:
            raise ProtocolError("goal_policy_busy")
        goal = self.goal
        if goal is None:
            raise ProtocolError("policy_goal_missing")
        if goal.kind not in self.provider.capabilities.kinds:
            self.set_goal(None)
            raise ProtocolError("unsupported_goal_conditioning")
        if (
            type(request) is not PolicyRequest
            or type(request.frame) is not PolicyFrame
            or not integer(request.request_id, 1, 2**53 - 1)
            or not finite(now, 0, float("inf"))
            or not finite(request.deadline, now, float("inf"))
            or request.deadline <= now
            or goal.expires_at <= now
        ):
            raise ProtocolError("expired_goal_request")
        if request.frame.capture_epoch != goal.capture_epoch:
            raise ProtocolError("goal_epoch_mismatch")
        generation = self.generation
        self.active = True
        try:
            result = await self.provider.predict_goal(GoalRequest(request, goal))
            if self.generation != generation or self.goal != goal:
                raise ProtocolError("policy_goal_changed")
            if self.clock() >= min(request.deadline, goal.expires_at):
                raise ProtocolError("expired_goal_result")
            if (
                type(result) is not GoalResult
                or result.goal != goal
                or type(result.observation) is not PolicyResult
                or type(result.observation.chunk) is not ActionChunk
                or result.observation.request_id != request.request_id
                or result.observation.capture_epoch != request.frame.capture_epoch
                or result.observation.receiver_sequence != request.frame.receiver_sequence
            ):
                raise ProtocolError("goal_result_binding_mismatch")
            return result.observation
        finally:
            self.active = False
