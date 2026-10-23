"""Untrusted VLM point claims, never Android commands or collision guarantees."""

from dataclasses import dataclass

from motor_worker.goals import Goal
from motor_worker.policy import PolicyFrame, PolicyRequest, epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer, message


@dataclass(frozen=True)
class VisualWaypoint:
    status: str
    side: str
    x: int
    y: int

    def __post_init__(self):
        if (
            type(self.status) is not str
            or self.status not in {"grounded", "unknown", "not_gameplay"}
            or type(self.side) is not str
            or self.side not in {"left", "center", "right", "none"}
            or not integer(self.x, 0, 1000)
            or not integer(self.y, 0, 1000)
            or self.status == "grounded" and self.side == "none"
            or self.status != "grounded" and (self.side != "none" or self.x != 0 or self.y != 0)
        ):
            raise ProtocolError("inconsistent_visual_waypoint")

    @classmethod
    def parse(cls, raw, *, finish_reason):
        if finish_reason != "stop":
            raise ProtocolError("incomplete_visual_waypoint")
        data = message(raw, 1024, strict_numbers=True)
        if data.keys() != {"status", "side", "x", "y"}:
            raise ProtocolError("invalid_visual_waypoint_schema")
        return cls(**data)


@dataclass(frozen=True)
class VisualReply:
    """Lineage is stamped by the trusted provider adapter, not by model text."""

    request_id: int
    capture_epoch: str
    receiver_sequence: int
    goal: Goal
    completed_at: float
    claim: VisualWaypoint

    def __post_init__(self):
        if (
            not integer(self.request_id, 1, 2**53 - 1)
            or not epoch_valid(self.capture_epoch)
            or not integer(self.receiver_sequence, 1, 2**53 - 1)
            or type(self.goal) is not Goal
            or type(self.claim) is not VisualWaypoint
            or not finite(self.completed_at, 0, float("inf"))
        ):
            raise ProtocolError("invalid_visual_reply")


def admit_visual_reply(reply, request, active_goal, *, now, max_receiver_age=0.4):
    """Return a fresh, exactly bound claim, or None. No physical authority.

    A returned point still requires independent scene/HUD masks, camera-to-stick
    calibration, local collision checks and a live native control lease. Slow
    planner replies cannot be promoted to fast motor corrections by renaming them.
    """
    if (
        type(reply) is not VisualReply
        or type(request) is not PolicyRequest
        or type(request.frame) is not PolicyFrame
        or not integer(request.request_id, 1, 2**53 - 1)
        or active_goal is not None and type(active_goal) is not Goal
        or not finite(now, 0, float("inf"))
        or not finite(max_receiver_age, 0.05, 0.5)
    ):
        raise ProtocolError("invalid_visual_admission")
    frame = request.frame
    if (
        active_goal is None
        or reply.goal != active_goal
        or reply.request_id != request.request_id
        or reply.capture_epoch != frame.capture_epoch
        or active_goal.capture_epoch != frame.capture_epoch
        or reply.receiver_sequence != frame.receiver_sequence
        or not finite(request.deadline, 0, float("inf"))
        or not frame.received_at <= reply.completed_at <= now
        or now >= min(request.deadline, active_goal.expires_at)
        or now - frame.received_at > max_receiver_age
        or reply.claim.status != "grounded"
    ):
        return None
    return reply.claim
