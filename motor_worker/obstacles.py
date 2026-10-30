"""Fresh image-space obstacle cues. No result of this module authorizes movement.

An overlapping box is a reason to inspect/stop, not proof of collision depth.
Missing detections, objects outside the ROI and unsupported labels remain unknown.
The caller stamps frame identity after inference on that exact RGB payload.
"""

import hashlib
import re
from dataclasses import dataclass

from motor_worker.policy import PolicyFrame, epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer


def _digest(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _box(value):
    return (
        type(value) is tuple
        and len(value) == 4
        and all(finite(v, 0, 1) for v in value)
        and value[0] < value[2]
        and value[1] < value[3]
    )


@dataclass(frozen=True)
class ObjectBox:
    label: str
    confidence: float
    xyxy: tuple[float, float, float, float]

    def __post_init__(self):
        if (
            type(self.label) is not str
            or not 1 <= len(self.label) <= 64
            or self.label != self.label.strip()
            or any(ord(c) < 32 for c in self.label)
            or not finite(self.confidence, 0, 1)
            or not _box(self.xyxy)
        ):
            raise ProtocolError("invalid_object_box")


@dataclass(frozen=True)
class ObjectObservation:
    capture_epoch: str
    receiver_sequence: int
    received_at: float
    completed_at: float
    profile_revision: str
    model_sha256: str
    pipeline_sha256: str
    rgb_sha256: str
    width: int
    height: int
    objects: tuple[ObjectBox, ...]

    def __post_init__(self):
        if (
            not epoch_valid(self.capture_epoch)
            or not epoch_valid(self.profile_revision)
            or not integer(self.receiver_sequence, 1, 2**53 - 1)
            or not finite(self.received_at, 0, float("inf"))
            or not finite(self.completed_at, self.received_at, float("inf"))
            or not _digest(self.model_sha256)
            or not _digest(self.pipeline_sha256)
            or not _digest(self.rgb_sha256)
            or not integer(self.width, 1, 4096)
            or not integer(self.height, 1, 4096)
            or self.width * self.height > 8 * 1024 * 1024
            or type(self.objects) is not tuple
            or len(self.objects) > 100
            or any(type(v) is not ObjectBox for v in self.objects)
        ):
            raise ProtocolError("invalid_object_observation")


@dataclass(frozen=True)
class ObstacleProfile:
    revision: str
    model_sha256: str
    pipeline_sha256: str
    roi: tuple[float, float, float, float]
    labels: frozenset[str]
    confidence: float = 0.25
    min_roi_overlap: float = 0.05

    def __post_init__(self):
        if (
            not epoch_valid(self.revision)
            or not _digest(self.model_sha256)
            or not _digest(self.pipeline_sha256)
            or not _box(self.roi)
            or type(self.labels) is not frozenset
            or not 1 <= len(self.labels) <= 64
            or any(type(v) is not str or not 1 <= len(v) <= 64 for v in self.labels)
            or not finite(self.confidence, 0.01, 1)
            or not finite(self.min_roi_overlap, 0.001, 1)
        ):
            raise ProtocolError("invalid_obstacle_profile")


@dataclass(frozen=True)
class ObstacleCue:
    status: str
    reason: str
    candidates: tuple[ObjectBox, ...] = ()


def inspect_obstacles(observation, frame, profile, *, now, scene_active, max_receiver_age=0.25):
    """Only 'suspected_obstacle' or 'unknown'; neither implies a free side/path.

    Receiver age includes inference and consumer delay, not Android capture age.
    A matching sequence alone is insufficient: dimensions and RGB digest bind the
    exact image, protecting against a cached or wrongly associated inference.
    """
    if (
        type(observation) is not ObjectObservation
        or type(frame) is not PolicyFrame
        or type(profile) is not ObstacleProfile
        or type(scene_active) is not bool
        or not finite(now, 0, float("inf"))
        or not finite(max_receiver_age, 0.05, 0.5)
    ):
        raise ProtocolError("invalid_obstacle_inspection")
    if (
        observation.capture_epoch != frame.capture_epoch
        or observation.receiver_sequence != frame.receiver_sequence
        or observation.received_at != frame.received_at
        or observation.width != frame.width
        or observation.height != frame.height
        or observation.rgb_sha256 != hashlib.sha256(frame.rgb24).hexdigest()
    ):
        return ObstacleCue("unknown", "frame_mismatch")
    # Same weights with a different backend/precision/tokenizer/preprocess are a
    # different pipeline. Qualification of FP32 must never authorize FP16 output.
    if (
        observation.profile_revision != profile.revision
        or observation.model_sha256 != profile.model_sha256
        or observation.pipeline_sha256 != profile.pipeline_sha256
    ):
        return ObstacleCue("unknown", "profile_mismatch")
    if not observation.received_at <= observation.completed_at <= now or now - observation.received_at > max_receiver_age:
        return ObstacleCue("unknown", "receiver_frame_stale")
    if not scene_active:
        return ObstacleCue("unknown", "gameplay_unconfirmed")
    x1, y1, x2, y2 = profile.roi
    area = (x2 - x1) * (y2 - y1)
    candidates = []
    for obj in observation.objects:
        if obj.label not in profile.labels or obj.confidence < profile.confidence:
            continue
        a, b, c, d = obj.xyxy
        overlap = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
        if overlap / area >= profile.min_roi_overlap:
            candidates.append(obj)
    if candidates:
        return ObstacleCue("suspected_obstacle", "image_roi_overlap_not_depth", tuple(candidates))
    return ObstacleCue("unknown", "no_obstacle_evidence_not_clearance")
