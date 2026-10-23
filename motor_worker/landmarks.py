"""Small, opt-in route-view memory. Image resemblance is not world localization.

No map discovery, path planning, depth, free-space claim or Android input. Profiles
must mask HUD/avatar regions. Repeated-looking places can remain ambiguous even
with geometric feature agreement; an executor needs route context and verification.
"""

import base64
import binascii
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass

from motor_worker.policy import PolicyFrame, epoch_valid, finite
from motor_worker.protocol import ProtocolError, integer, message

SIZE = (480, 270)
MAX_FEATURES = 1500


def _rect(v):
    return (
        type(v) is tuple and len(v) == 4
        and all(finite(x, 0, 1) for x in v) and v[0] < v[2] and v[1] < v[3]
    )


def _sha(v):
    return type(v) is str and re.fullmatch(r"[0-9a-f]{64}", v) is not None


@dataclass(frozen=True)
class RouteViewProfile:
    revision: str
    width: int
    height: int
    roi: tuple[float, float, float, float]
    excluded: tuple[tuple[float, float, float, float], ...]

    def encode(self):
        return json.dumps({"schema_version": 1, **asdict(self)}, separators=(",", ":"))

    @classmethod
    def parse(cls, raw):
        data = message(raw, 4096, strict_numbers=True)
        if (data.keys() != {"schema_version", "revision", "width", "height", "roi", "excluded"}
                or not integer(data["schema_version"], 1, 1)
                or type(data["roi"]) is not list or type(data["excluded"]) is not list
                or any(type(r) is not list for r in data["excluded"])):
            raise ProtocolError("invalid_route_view_profile_schema")
        data.pop("schema_version")
        data["roi"] = tuple(data["roi"])
        data["excluded"] = tuple(tuple(r) for r in data["excluded"])
        return cls(**data)

    def __post_init__(self):
        if (
            not epoch_valid(self.revision)
            or not integer(self.width, 16, 4096) or not integer(self.height, 16, 4096)
            or self.width * self.height > 8 * 1024 * 1024
            or not _rect(self.roi)
            or type(self.excluded) is not tuple or not 1 <= len(self.excluded) <= 16
            or any(not _rect(v) for v in self.excluded)
        ):
            raise ProtocolError("invalid_route_view_profile")


@dataclass(frozen=True)
class RouteKeyframe:
    id: str
    profile_revision: str
    pipeline_sha256: str
    image_sha256: str
    source_epoch: str
    source_sequence: int
    points: tuple[tuple[float, float], ...]
    descriptors: bytes

    def __post_init__(self):
        if (
            not all(epoch_valid(v) for v in (self.id, self.profile_revision, self.source_epoch))
            or not integer(self.source_sequence, 1, 2**53 - 1)
            or not _sha(self.pipeline_sha256) or not _sha(self.image_sha256)
            or type(self.points) is not tuple or not 24 <= len(self.points) <= MAX_FEATURES
            or any(type(p) is not tuple or len(p) != 2
                   or not finite(p[0], 0, SIZE[0]) or not finite(p[1], 0, SIZE[1]) for p in self.points)
            or type(self.descriptors) is not bytes or len(self.descriptors) != len(self.points) * 32
        ):
            raise ProtocolError("invalid_route_keyframe")

    def encode(self):
        """Explicit export of bounded features; contains no RGB image or commands."""
        data = asdict(self)
        data["descriptors"] = base64.b64encode(self.descriptors).decode("ascii")
        return json.dumps({"schema_version": 1, **data}, separators=(",", ":"))

    @classmethod
    def parse(cls, raw):
        data = message(raw, 256*1024, strict_numbers=True)
        expected = {"id", "profile_revision", "pipeline_sha256", "image_sha256",
                    "source_epoch", "source_sequence", "points", "descriptors", "schema_version"}
        if (data.keys() != expected or not integer(data["schema_version"], 1, 1)
                or type(data["points"]) is not list or len(data["points"]) > MAX_FEATURES
                or any(type(p) is not list or len(p) != 2 for p in data["points"])
                or type(data["descriptors"]) is not str or len(data["descriptors"]) > 64000):
            raise ProtocolError("invalid_route_keyframe_schema")
        data.pop("schema_version")
        data["points"] = tuple(tuple(p) for p in data["points"])
        try:
            data["descriptors"] = base64.b64decode(data["descriptors"], validate=True)
        except (ValueError, binascii.Error):
            raise ProtocolError("invalid_route_keyframe_encoding") from None
        return cls(**data)


@dataclass(frozen=True)
class RouteViewMatch:
    status: str
    reason: str
    capture_epoch: str
    receiver_sequence: int
    profile_revision: str
    pipeline_sha256: str
    received_at: float
    completed_at: float
    keyframe_id: str | None = None
    inliers: int = 0


class RouteViewMatcher:
    """Bounded CPU observer with no learned weights and no physical authority.

    Keyframes store <=1500 descriptors, not RGB/video. Compare <=16 route-context
    candidates, not a global map search. A second passing reference refuses a
    choice; one passing reference is still only visual resemblance, not pose.
    """

    def __init__(self, profile, *, clock=time.perf_counter):
        if type(profile) is not RouteViewProfile or not callable(clock):
            raise ProtocolError("invalid_route_view_matcher")
        import cv2
        import numpy as np

        self.cv, self.np, self.profile, self.clock = cv2, np, profile, clock
        identity = {"algorithm": "orb-route-view-v1", "opencv": cv2.__version__,
                    "profile": asdict(profile), "analysisSize": SIZE,
                    "maxFeatures": MAX_FEATURES, "ratio": 0.7, "hammingBelow": 60,
                    "patchSize": 15, "levels": 4, "maskMarginPx": 16,
                    "ransacPx": 3, "minInliers": 24, "minInlierFraction": 0.65,
                    "gridCells": 4, "maxReferences": 16}
        self.pipeline_sha256 = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self.mask = np.zeros((SIZE[1], SIZE[0]), np.uint8)
        for rect, value in ((profile.roi, 255), *((r, 0) for r in profile.excluded)):
            a, b, c, d = rect
            self.mask[int(b*SIZE[1]):int(d*SIZE[1]), int(a*SIZE[0]):int(c*SIZE[0])] = value
        # Pad exclusions to reduce descriptor leakage at region edges. This is
        # a view-matching mask, not semantic foreground isolation.
        self.mask = cv2.erode(self.mask, np.ones((33, 33), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
        self.mask.setflags(write=False)

    def _fresh(self, frame):
        if type(frame) is not PolicyFrame:
            raise ProtocolError("invalid_route_view_frame")
        now = self.clock()
        if not finite(now, 0, float("inf")):
            raise ProtocolError("invalid_route_view_clock")
        return ((frame.width, frame.height) == (self.profile.width, self.profile.height)
                and 0 <= now - frame.received_at <= 0.25)

    def _features(self, frame):
        cv, np = self.cv, self.np
        rgb = np.frombuffer(frame.rgb24, np.uint8).reshape(frame.height, frame.width, 3)
        gray = cv.resize(cv.cvtColor(rgb, cv.COLOR_RGB2GRAY), SIZE)
        # An instance per call avoids sharing a mutable extractor across callers.
        return cv.ORB_create(nfeatures=MAX_FEATURES, edgeThreshold=10, fastThreshold=12,
                             patchSize=15, nlevels=4).detectAndCompute(gray, self.mask)

    def learn(self, frame, *, keyframe_id):
        if not epoch_valid(keyframe_id):
            raise ProtocolError("invalid_route_keyframe_id")
        if not self._fresh(frame):
            return None
        points, descriptors = self._features(frame)
        if descriptors is None or len(points) < 24 or not self._fresh(frame):
            return None
        return RouteKeyframe(keyframe_id, self.profile.revision, self.pipeline_sha256,
                             hashlib.sha256(frame.rgb24).hexdigest(), frame.capture_epoch,
                             frame.receiver_sequence, tuple(tuple(p.pt) for p in points), descriptors.tobytes())

    def compare(self, frame, references):
        if (type(references) is not tuple or not 1 <= len(references) <= 16
                or any(type(r) is not RouteKeyframe for r in references)
                or len({r.id for r in references}) != len(references)):
            raise ProtocolError("invalid_route_view_references")
        fresh = self._fresh(frame)

        def result(reason, reference=None, inliers=0):
            return RouteViewMatch("matched" if reference else "unknown", reason,
                                  frame.capture_epoch, frame.receiver_sequence, self.profile.revision,
                                  self.pipeline_sha256, frame.received_at, self.clock(),
                                  reference.id if reference else None, inliers)

        if not fresh:
            return result("stale_or_wrong_geometry")
        if any(r.profile_revision != self.profile.revision or r.pipeline_sha256 != self.pipeline_sha256 for r in references):
            return result("reference_profile_mismatch")
        cv, np = self.cv, self.np
        points, descriptors = self._features(frame)
        if descriptors is None or len(points) < 24:
            return result("insufficient_scene_features")
        hits = []
        for reference in references:
            ref = np.frombuffer(reference.descriptors, np.uint8).reshape(-1, 32)
            pairs = cv.BFMatcher(cv.NORM_HAMMING).knnMatch(ref, descriptors, k=2)
            good = [m for pair in pairs if len(pair) == 2 for m, n in [pair]
                    if m.distance < 0.7*n.distance and m.distance < 60]
            # Each correspondence must have a distinct scene feature.
            good = list({m.trainIdx: m for m in sorted(good, key=lambda m: m.distance, reverse=True)}.values())
            if len(good) < 24:
                continue
            src = np.float32([reference.points[m.queryIdx] for m in good])
            dst = np.float32([points[m.trainIdx].pt for m in good])
            h, mask = cv.findHomography(src, dst, cv.RANSAC, 3, maxIters=500, confidence=0.99)
            if h is None or mask is None or not np.isfinite(h).all():
                continue
            keep = mask[:, 0].astype(bool)
            count = int(keep.sum())
            coverage = [len({(int(x//120), int(y//90)) for x, y in values[keep]}) for values in (src, dst)]
            corners = np.float32([[[0, 0], [480, 0], [480, 270], [0, 270]]])
            projected = cv.perspectiveTransform(corners, h)[0]
            sane = (np.isfinite(projected).all() and cv.isContourConvex(projected)
                    and 0.4 <= cv.contourArea(projected, oriented=True) / (480*270) <= 2.5)
            if count >= 24 and count/len(good) >= 0.65 and min(coverage) >= 4 and sane:
                hits.append((reference, count))
        if not self._fresh(frame):
            return result("receiver_frame_expired_during_match")
        if len(hits) != 1:
            return result("ambiguous_route_views" if hits else "no_route_view_match")
        return result("image_resemblance_not_pose_or_clearance", *hits[0])
