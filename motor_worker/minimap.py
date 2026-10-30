"""Calibrated, bounded GPS-line observations. No Android input or world inference.

The line supplies local route geometry, not collision clearance, vehicle steering
or arrival. Ambiguous branches, missing pixels and unknown orientation refuse a
direction. There is no game name, package, network call or hard-coded HUD here.
"""

from __future__ import annotations

import asyncio
import heapq
import math
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Callable

from motor_worker.policy import (
    ActionChunk,
    GamepadState,
    PolicyFrame,
    PolicyRequest,
    PolicyResult,
    epoch_valid,
    finite,
)
from motor_worker.protocol import ProtocolError, integer, message


@dataclass(frozen=True)
class MinimapProfile:
    """All pixel positions are in an explicitly sized original RGB frame.

    Center coordinates are ROI-relative. forward_degrees is the calibrated
    screen-space heading: 0 points up, +90 right. None is deliberately unknown.
    Hue is OpenCV's 0..179; a lower hue above upper hue means wraparound red.
    """

    frame_width: int
    frame_height: int
    roi: tuple[int, int, int, int]
    center: tuple[int, int]
    radius: int
    player_radius: int
    hsv_lower: tuple[int, int, int]
    hsv_upper: tuple[int, int, int]
    forward_degrees: float | None = None
    lookahead_px: float = 30
    max_anchor_gap_px: float = 8
    min_path_px: float = 10
    max_frontier_spread_degrees: float = 35

    @classmethod
    def parse(cls, raw: str) -> MinimapProfile:
        data = message(raw, 4096, strict_numbers=True)
        fields = {
            "frame_width",
            "frame_height",
            "roi",
            "center",
            "radius",
            "player_radius",
            "hsv_lower",
            "hsv_upper",
            "forward_degrees",
            "lookahead_px",
            "max_anchor_gap_px",
            "min_path_px",
            "max_frontier_spread_degrees",
        }
        if data.keys() != fields | {"schema_version"} or not integer(data["schema_version"], 1, 1):
            raise ProtocolError("invalid_minimap_profile_schema")
        data.pop("schema_version")
        for name in ("roi", "center", "hsv_lower", "hsv_upper"):
            if type(data[name]) is not list:
                raise ProtocolError("invalid_minimap_profile_schema")
            data[name] = tuple(data[name])
        return cls(**data)

    def __post_init__(self):
        if (
            not integer(self.frame_width, 16, 4096)
            or not integer(self.frame_height, 16, 4096)
            or type(self.roi) is not tuple
            or len(self.roi) != 4
            or type(self.center) is not tuple
            or len(self.center) != 2
        ):
            raise ProtocolError("invalid_minimap_profile")
        x, y, w, h = self.roi
        if (
            not integer(w, 16, 256)
            or not integer(h, 16, 256)
            or not integer(x, 0, self.frame_width - w)
            or not integer(y, 0, self.frame_height - h)
            or not integer(self.radius, 6, min(w, h) // 2 - 1)
            or not integer(self.player_radius, 1, self.radius - 4)
            or not integer(self.center[0], self.radius, w - self.radius - 1)
            or not integer(self.center[1], self.radius, h - self.radius - 1)
            or self.forward_degrees is not None
            and not finite(self.forward_degrees, -180, 180)
            or not finite(self.lookahead_px, 8, 128)
            or not finite(self.min_path_px, 6, self.lookahead_px)
            or not finite(self.max_anchor_gap_px, 1, self.radius - self.player_radius)
            or not finite(self.max_frontier_spread_degrees, 10, 60)
        ):
            raise ProtocolError("invalid_minimap_profile")
        for bound in (self.hsv_lower, self.hsv_upper):
            if (
                type(bound) is not tuple
                or len(bound) != 3
                or not integer(bound[0], 0, 179)
                or any(not integer(v, 0, 255) for v in bound[1:])
            ):
                raise ProtocolError("invalid_minimap_color")
        if any(self.hsv_lower[i] > self.hsv_upper[i] for i in (1, 2)):
            raise ProtocolError("invalid_minimap_color")


@dataclass(frozen=True)
class RouteGeometry:
    reason: str
    path: tuple[tuple[int, int], ...] = ()
    heading_error_degrees: float | None = None
    path_length_px: float = 0
    route_pixels: int = 0

    @property
    def direction_available(self):
        return self.reason == "route_observed" and self.heading_error_degrees is not None


def _angular_span(angles):
    ordered = sorted(a % 360 for a in angles)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    gaps.append(ordered[0] + 360 - ordered[-1])
    return 360 - max(gaps)


def extract_route(frame: PolicyFrame, profile: MinimapProfile) -> RouteGeometry:
    """Follow only connected colored pixels, never a chord through a corner.

    OpenCV supplies RGB/HSV conversion and 8-connected component labels. A
    bounded Dijkstra layer supplies path-distance lookahead without introducing
    a thinning dependency or bridging missing road pixels by morphology.
    """
    import cv2
    import numpy as np

    if (
        type(frame) is not PolicyFrame
        or type(profile) is not MinimapProfile
        or (frame.width, frame.height) != (profile.frame_width, profile.frame_height)
    ):
        raise ProtocolError("minimap_frame_geometry_mismatch")
    left, top, width, height = profile.roi
    rgb = np.frombuffer(frame.rgb24, dtype=np.uint8).reshape(frame.height, frame.width, 3)
    hsv = cv2.cvtColor(rgb[top : top + height, left : left + width], cv2.COLOR_RGB2HSV)
    lo, hi = profile.hsv_lower, profile.hsv_upper
    if lo[0] <= hi[0]:
        mask = cv2.inRange(hsv, lo, hi)
    else:
        mask = cv2.inRange(hsv, (0, lo[1], lo[2]), hi) | cv2.inRange(hsv, lo, (179, hi[1], hi[2]))
    yy, xx = np.indices((height, width))
    cx, cy = profile.center
    radial_sq = (xx - cx) ** 2 + (yy - cy) ** 2
    mask[(radial_sq > profile.radius**2) | (radial_sq <= profile.player_radius**2)] = 0
    # Reject a broad same-colored region before graph work, bounded to 4096 nodes.
    pixels = int(np.count_nonzero(mask))
    if pixels > 4096 or pixels > math.pi * profile.radius**2 * 0.25:
        return RouteGeometry("route_mask_too_dense", route_pixels=pixels)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    candidates = []
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < 12:
            continue
        ys, xs = np.where(labels == label)
        nearest_sq = int(radial_sq[ys, xs].min())
        if math.sqrt(nearest_sq) <= profile.player_radius + profile.max_anchor_gap_px:
            candidates.append((label, nearest_sq, xs, ys))
    if not candidates:
        return RouteGeometry("route_not_anchored", route_pixels=pixels)
    if len(candidates) != 1:
        return RouteGeometry("route_anchor_ambiguous", route_pixels=pixels)
    label, nearest_sq, xs, ys = candidates[0]
    seeds = [
        (int(x), int(y))
        for x, y in zip(xs, ys)
        if radial_sq[y, x] <= (math.sqrt(nearest_sq) + 1.0) ** 2
    ]
    angles = [math.degrees(math.atan2(x - cx, cy - y)) for x, y in seeds]
    # A thick route occupies a wide angle immediately outside the player disk.
    # Only opposing anchor directions are ambiguous here; the longer lookahead
    # layer below distinguishes actual forks without rejecting line thickness.
    if _angular_span(angles) > 90:
        return RouteGeometry("route_anchor_ambiguous", route_pixels=pixels)
    mx, my = sum(x for x, _ in seeds) / len(seeds), sum(y for _, y in seeds) / len(seeds)
    start = min(seeds, key=lambda p: ((p[0] - mx) ** 2 + (p[1] - my) ** 2, p))
    distance, previous, queue = {start: 0.0}, {}, [(0.0, start)]
    neighbors = tuple(
        (dx, dy, math.hypot(dx, dy)) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy
    )
    while queue:
        length, point = heapq.heappop(queue)
        if length != distance[point]:
            continue
        x, y = point
        for dx, dy, step in neighbors:
            next_point = nx, ny = x + dx, y + dy
            next_length = length + step
            if (
                0 <= nx < width
                and 0 <= ny < height
                and labels[ny, nx] == label
                and next_length <= profile.lookahead_px
                and next_length < distance.get(next_point, math.inf)
            ):
                distance[next_point], previous[next_point] = next_length, point
                heapq.heappush(queue, (next_length, next_point))
    length = max(distance.values())
    if length < profile.min_path_px:
        return RouteGeometry("route_too_short_not_arrival", route_pixels=pixels)
    frontier = [p for p, d in distance.items() if d >= length - 1.5]
    angles = [math.degrees(math.atan2(x - cx, cy - y)) for x, y in frontier]
    if _angular_span(angles) > profile.max_frontier_spread_degrees:
        return RouteGeometry("route_frontier_ambiguous", route_pixels=pixels)
    mx = sum(x for x, _ in frontier) / len(frontier)
    my = sum(y for _, y in frontier) / len(frontier)
    target = min(frontier, key=lambda p: ((p[0] - mx) ** 2 + (p[1] - my) ** 2, p))
    path, point = [target], target
    while point != start:
        point = previous[point]
        path.append(point)
    path = tuple((x + left, y + top) for x, y in reversed(path))
    if profile.forward_degrees is None:
        return RouteGeometry(
            "orientation_not_calibrated", path, path_length_px=distance[target], route_pixels=pixels
        )
    bearing = math.degrees(math.atan2(target[0] - cx, cy - target[1]))
    error = (bearing - profile.forward_degrees + 180) % 360 - 180
    return RouteGeometry("route_observed", path, error, distance[target], pixels)


class MinimapRouteShadow:
    """Read-only Policy bridge for real Sphere RGB frames; always neutral output.

    Reported directions are observations, never commands. The physical executor
    explicitly refuses this provider. A new capture epoch requires a new instance.
    """

    def __init__(
        self,
        profile: MinimapProfile,
        *,
        goal_revision: str,
        clock: Callable[[], float] = time.perf_counter,
    ):
        if type(profile) is not MinimapProfile or not epoch_valid(goal_revision):
            raise ProtocolError("invalid_minimap_shadow_config")
        self.profile, self.goal_revision, self.clock = profile, goal_revision, clock
        self.epoch = None
        self.last_sequence = 0
        self.terminal = False
        self.closed = False
        self.job: asyncio.Task | None = None
        self.reasons: Counter[str] = Counter()
        self.samples: deque[dict] = deque(maxlen=64)

    async def predict(self, request: PolicyRequest) -> PolicyResult:
        if (
            self.closed
            or type(request) is not PolicyRequest
            or not integer(request.request_id, 1, 2**53 - 1)
        ):
            raise ProtocolError("invalid_minimap_request")
        if self.job is not None and not self.job.done():
            raise ProtocolError("route_analysis_busy")
        frame, before = request.frame, self.clock()
        if type(frame) is not PolicyFrame or not finite(request.deadline, 0, float("inf")):
            raise ProtocolError("invalid_minimap_request")
        if self.epoch is None:
            self.epoch = frame.capture_epoch
        if frame.capture_epoch != self.epoch or frame.receiver_sequence <= self.last_sequence:
            self.terminal = True
        self.last_sequence = frame.receiver_sequence
        result = RouteGeometry("route_session_changed")
        analysis_ms = None
        if not self.terminal:
            if not 0 <= before - frame.received_at <= 0.25 or before >= request.deadline:
                result = RouteGeometry("route_frame_stale")
            else:
                # Cancellation of to_thread cannot stop OpenCV/Python work.
                # Keep its actual task shielded and join before acknowledging
                # cancellation. The outer policy loop bounds that retirement;
                # an unfinished job also fences new requests on this instance.
                self.job = asyncio.create_task(
                    asyncio.to_thread(extract_route, frame, self.profile)
                )
                try:
                    result = await asyncio.shield(self.job)
                except asyncio.CancelledError:
                    await asyncio.shield(self.job)
                    raise
                after = self.clock()
                analysis_ms = round((after - before) * 1000, 3) if after >= before else None
                if (
                    after < before
                    or not 0 <= after - frame.received_at <= 0.25
                    or after >= request.deadline
                ):
                    result = RouteGeometry("route_analysis_expired")
        self.reasons[result.reason] += 1
        self.samples.append(
            {
                "receiverSequence": frame.receiver_sequence,
                "reason": result.reason,
                "headingErrorDegrees": round(result.heading_error_degrees, 3)
                if result.heading_error_degrees is not None
                else None,
                "pathLengthPixels": round(result.path_length_px, 3),
                "routePixels": result.route_pixels,
                "analysisWallMs": analysis_ms,
            }
        )
        return PolicyResult(
            request.request_id,
            frame.capture_epoch,
            frame.receiver_sequence,
            ActionChunk((GamepadState.neutral(),), 20),
        )

    def report(self):
        return {
            "kind": "MINIMAP_ROUTE_SHADOW_NOT_DRIVING_OR_CLEARANCE",
            "physicalExecutionSupported": False,
            "goalRevision": self.goal_revision,
            "reasons": dict(self.reasons),
            "sampleTailLimit": 64,
            "samples": list(self.samples),
            "sourceCaptureAgeMeasured": False,
            "obstacleClearanceMeasured": False,
            "arrivalMeasured": False,
            "backgroundJobRetired": self.job is None or self.job.done(),
        }

    async def close(self):
        self.closed = True
        if self.job is not None:
            try:
                await asyncio.shield(self.job)
            except Exception:
                # predict() owns the analysis error. A completed failed task is
                # retired; cleanup must not mask that original failure.
                pass
