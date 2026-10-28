"""Experimental sparse-map relocalization and same-frame route projection.

Independent of recorded keys and dense meshes. A pose is relative to the supplied
map, not a claim that the map is correct, metric, traversable or goal-conditioned.
This module has no executor, network, model or Android input authority.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from motor_worker.landmarks import RouteViewProfile
from motor_worker.policy import PolicyFrame, epoch_valid, finite
from motor_worker.protocol import ProtocolError, message

SIZE = (960, 540)
# Changes to the runtime pose gate are tracked separately from the descriptor
# format: strengthening a gate must not make compatible saved maps unreadable.
PNP_VERIFICATION_POLICY = 'pnp-image-coverage-temporal-v3'
MAX_POINTS = 4096
MAX_VIEWS = 256
MAX_BYTES = 4 * 1024 * 1024
# An absent camera over a longer interval is not evidence of a continuous route.
# This conservative policy can reject sparse recordings; it does not prove that
# shorter intervals are traversable or that the camera trace follows the road.
MAX_REFERENCE_INTERVAL_SECONDS = 1.0


def _sha(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _vectors(values, count, width):
    return (type(values) is tuple and len(values) == count
            and all(type(row) is tuple and len(row) == width
                    and all(finite(v, -1e8, 1e8) for v in row) for row in values))


def pipeline_id():
    import cv2

    # Different extractor versions/settings require rebuilding the map.
    return hashlib.sha256(json.dumps(dict(
        version=2, opencv=cv2.__version__, size=SIZE, sift_features=2048,
        contrast=.0066667, edge=10, descriptor="rootsift", ratio=.75,
        min_inliers=20, inlier_fraction=.5, ransac_px=3, mask_margin=8, covisibility_candidates=3,
    ), sort_keys=True).encode()).hexdigest()


def feature_mask(profile):
    import cv2 as cv
    import numpy as np

    mask = np.zeros((SIZE[1], SIZE[0]), np.uint8)
    for rect, value in ((profile.roi, 255), *((r, 0) for r in profile.excluded)):
        a, b, c, d = rect
        mask[int(b*SIZE[1]):int(d*SIZE[1]), int(a*SIZE[0]):int(c*SIZE[0])] = value
    return cv.erode(mask, np.ones((17, 17), np.uint8), borderType=cv.BORDER_CONSTANT, borderValue=0)


def extract_features(frame, mask):
    """Identical teaching/query extraction resolution and descriptor transform."""
    import cv2 as cv
    import numpy as np

    rgb = np.frombuffer(frame.rgb24, np.uint8).reshape(frame.height, frame.width, 3)
    gray = cv.resize(cv.cvtColor(rgb, cv.COLOR_RGB2GRAY), SIZE, interpolation=cv.INTER_AREA)
    points, desc = cv.SIFT_create(nfeatures=2048, contrastThreshold=.0066667, edgeThreshold=10).detectAndCompute(gray, mask)
    if desc is None:
        return np.empty((0, 2)), np.empty((0, 128), np.float32)
    desc = np.sqrt(desc/np.maximum(desc.sum(axis=1, keepdims=True), 1e-8))
    desc /= np.maximum(np.linalg.norm(desc, axis=1, keepdims=True), 1e-8)
    return np.float64([p.pt for p in points]), desc.astype(np.float32)


def inlier_spatial_support(points):
    """Require inliers across both image axes, not one textured strip.

    This is a conservative image-space observability check. It does not prove
    that points are static, the pose is correct, or the road is traversable.
    """
    import numpy as np

    xy=np.asarray(points,dtype=np.float64)
    if (xy.ndim!=2 or xy.shape[1]!=2 or len(xy)<20 or not np.isfinite(xy).all()
            or (xy<0).any() or (xy[:,0]>=SIZE[0]).any() or (xy[:,1]>=SIZE[1]).any()):
        return False
    cells={(int(x//240),int(y//180)) for x,y in xy}
    minimum=max(5,int(np.ceil(len(xy)*.05)))
    columns=np.bincount((xy[:,0]//240).astype(int),minlength=4)
    rows=np.bincount((xy[:,1]//180).astype(int),minlength=3)
    if len(cells)<4 or int((columns>=minimum).sum())<2 or int((rows>=minimum).sum())<2:
        return False
    spread=np.percentile(xy,95,axis=0)-np.percentile(xy,5,axis=0)
    return bool(spread[0]>=96 and spread[1]>=54)


def map_support(route):
    """Necessary feature coverage, not a localization/road-quality guarantee."""
    import numpy as np

    if type(route) is not SparseRoute:
        raise ProtocolError("invalid_sparse_route_support")
    visibility = np.zeros((len(route.camera_trace), len(route.points)), np.uint8)
    for point, views in enumerate(route.landmark_views):
        visibility[list(views), point] = 1
    per_view = visibility.sum(axis=1)
    neighborhoods = np.asarray([np.any(visibility[max(0, at-1):at+2], axis=0).sum()
                                for at in range(len(visibility))])
    longest, run = 0., None
    for index, supported in enumerate(neighborhoods >= 24):
        if not supported:
            run = index if run is None else run
            longest = max(longest, route.source_seconds[index]-route.source_seconds[run])
        else:
            run = None
    gaps = [index for index, (first, second) in enumerate(zip(route.source_seconds, route.source_seconds[1:]))
            if second-first > MAX_REFERENCE_INTERVAL_SECONDS]
    return dict(reference_views=len(visibility), min_correspondences_required=24,
        per_view_landmarks=[int(v) for v in per_view], neighborhood_landmarks=[int(v) for v in neighborhoods],
        views_below_24=int((per_view < 24).sum()), neighborhoods_below_24=int((neighborhoods < 24).sum()),
        zero_landmark_views=int((per_view == 0).sum()),
        longest_unsupported_reference_span_seconds=float(longest),
        all_reference_neighborhoods_supported=bool(np.all(neighborhoods >= 24)),
        reference_interval_limit_seconds=MAX_REFERENCE_INTERVAL_SECONDS,
        unobserved_intervals=[dict(start_seconds=route.source_seconds[index],
                                   end_seconds=route.source_seconds[index+1]) for index in gaps],
        all_reference_intervals_observed=not gaps,
        navigation_qualified=False)


@dataclass(frozen=True)
class SparseRoute:
    """One bounded submap. Long routes must split, never silently truncate.

    Coordinates share one SfM frame. The ordered trace is of the CAMERA, not
    surveyed road/lane/character coordinates. metres_per_unit is intentionally
    absent: no monocular recording can supply it without an external reference.
    """

    id: str
    world_revision: str
    source_sha256: str
    pipeline_sha256: str
    profile: RouteViewProfile
    intrinsics: tuple[float, float, float, float]  # fx, fy, cx, cy at SIZE
    points: tuple[tuple[float, float, float], ...]
    descriptors: bytes  # one RootSIFT float32[128] per 3D landmark
    camera_trace: tuple[tuple[float, float, float], ...]
    source_seconds: tuple[float, ...]
    reference_rgb_sha256: tuple[str, ...]
    landmark_views: tuple[tuple[int, ...], ...]
    source_capture_sha256: str
    source_frame_indices: tuple[int, ...]

    def __post_init__(self):
        import numpy as np

        if (not epoch_valid(self.id) or not epoch_valid(self.world_revision)
                or not _sha(self.source_sha256) or not _sha(self.pipeline_sha256)
                or type(self.profile) is not RouteViewProfile
                or self.profile.width * SIZE[1] != self.profile.height * SIZE[0]
                or type(self.intrinsics) is not tuple or len(self.intrinsics) != 4
                or any(not finite(v, 1, 10000) for v in self.intrinsics[:2])
                or not finite(self.intrinsics[2], 0, SIZE[0]) or not finite(self.intrinsics[3], 0, SIZE[1])
                or type(self.points) is not tuple or not 24 <= len(self.points) <= MAX_POINTS
                or not _vectors(self.points, len(self.points), 3)
                or type(self.camera_trace) is not tuple or not 2 <= len(self.camera_trace) <= MAX_VIEWS
                or not _vectors(self.camera_trace, len(self.camera_trace), 3)
                or type(self.source_seconds) is not tuple or len(self.source_seconds) != len(self.camera_trace)
                or any(not finite(v, 0, 600) for v in self.source_seconds)
                or any(b <= a for a, b in zip(self.source_seconds, self.source_seconds[1:]))
                or type(self.reference_rgb_sha256) is not tuple
                or len(self.reference_rgb_sha256) != len(self.camera_trace)
                or any(not _sha(v) for v in self.reference_rgb_sha256)
                or not _sha(self.source_capture_sha256)
                or type(self.source_frame_indices) is not tuple or len(self.source_frame_indices) != len(self.camera_trace)
                or any(type(v) is not int or not 0 <= v <= 72000 for v in self.source_frame_indices)
                or any(b <= a for a, b in zip(self.source_frame_indices, self.source_frame_indices[1:]))
                or type(self.landmark_views) is not tuple or len(self.landmark_views) != len(self.points)
                or any(type(row) is not tuple or not 3 <= len(row) <= len(self.camera_trace)
                       or any(type(v) is not int or not 0 <= v < len(self.camera_trace) for v in row)
                       or tuple(sorted(set(row))) != row for row in self.landmark_views)
                or type(self.descriptors) is not bytes or len(self.descriptors) != len(self.points)*128*4):
            raise ProtocolError("invalid_sparse_route")
        desc = np.frombuffer(self.descriptors, dtype="<f4").reshape(-1, 128)
        steps = np.linalg.norm(np.diff(self.camera_trace, axis=0), axis=1)
        if (not np.isfinite(desc).all() or (desc < 0).any() or (desc > 1).any()
                or not np.allclose(np.linalg.norm(desc, axis=1), 1, atol=.02)
                or (steps < 1e-6).any()):
            raise ProtocolError("invalid_sparse_route_geometry_or_descriptors")

    def save(self, path):
        data = asdict(self)
        data["descriptors"] = base64.b64encode(self.descriptors).decode("ascii")
        data.update(schema="sphere-sparse-route-v1", camera_trace_only=True, execution_qualified=False)
        raw = (json.dumps(data, allow_nan=False, separators=(",", ":"))+"\n").encode()
        if len(raw) > MAX_BYTES:
            raise ProtocolError("sparse_route_file_quota")
        with Path(path).open("xb") as out:
            out.write(raw)
        return hashlib.sha256(raw).hexdigest()

    @classmethod
    def load(cls, path, *, sha256):
        path = Path(path)
        if not _sha(sha256) or path.is_symlink() or not path.is_file():
            raise ProtocolError("sparse_route_unavailable")
        with path.open("rb") as file:
            raw = file.read(MAX_BYTES+1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != sha256:
            raise ProtocolError("sparse_route_integrity")
        try:
            data = message(raw.decode("utf-8"), MAX_BYTES, strict_numbers=True)
        except UnicodeDecodeError:
            raise ProtocolError("sparse_route_encoding") from None
        fields = set(cls.__dataclass_fields__) | {"schema", "camera_trace_only", "execution_qualified"}
        if (data.keys() != fields or data.pop("schema") != "sphere-sparse-route-v1"
                or data.pop("camera_trace_only") is not True or data.pop("execution_qualified") is not False):
            raise ProtocolError("sparse_route_schema")
        try:
            data["descriptors"] = base64.b64decode(data["descriptors"], validate=True)
            data["profile"] = RouteViewProfile.parse(json.dumps(dict(schema_version=1, **data["profile"])))
            for name in ("points", "camera_trace", "landmark_views"):
                data[name] = tuple(tuple(row) for row in data[name])
            for name in ("source_seconds", "reference_rgb_sha256", "intrinsics", "source_frame_indices"):
                data[name] = tuple(data[name])
        except (ValueError, TypeError, KeyError, binascii.Error):
            raise ProtocolError("sparse_route_schema") from None
        return cls(**data)


@dataclass(frozen=True)
class RoutePose:
    state: str
    reason: str
    route_id: str
    world_revision: str
    capture_epoch: str
    receiver_sequence: int
    received_at: float
    completed_at: float
    source_rgb_sha256: str
    geometry: tuple[int, int]
    center: tuple[float, float, float] | None = None
    rotation: tuple[float, ...] | None = None  # world -> camera, row-major
    segment: int | None = None
    progress_units: float | None = None
    cross_track_units: float | None = None
    inliers: int = 0
    median_error_px: float | None = None
    polyline_px: tuple[tuple[float, float], ...] = ()


class RouteLocalizer:
    """Global search within a submap; no first-view/start-pose requirement.

    Frame/episode/goal binding, 250ms receiver-age gate and three consistent
    independent observations are required. Lost observations clear confirmation.
    Real-world aliases and map quality still need independent qualification.
    """

    def __init__(self, route, *, capture_epoch, episode_id, goal_revision, clock=time.monotonic,
                 diagnostic_partial_map=False, candidate_limit=3):
        import cv2 as cv
        import numpy as np

        if (type(diagnostic_partial_map) is not bool or type(candidate_limit) is not int or not 3 <= candidate_limit <= 8
                or type(route) is not SparseRoute or not all(epoch_valid(v) for v in
                (capture_epoch, episode_id, goal_revision)) or route.pipeline_sha256 != pipeline_id()):
            raise ProtocolError("invalid_route_localizer_binding")
        if not diagnostic_partial_map:
            support = map_support(route)
            if not support["all_reference_neighborhoods_supported"] or not support["all_reference_intervals_observed"]:
                raise ProtocolError("route_map_has_unobserved_sections")
        self.route, self.epoch, self.episode, self.goal, self.clock = route, capture_epoch, episode_id, goal_revision, clock
        self.candidate_limit = candidate_limit
        self.cv, self.np = cv, np
        self.xyz = np.asarray(route.points, np.float64)
        self.descriptors = np.frombuffer(route.descriptors, dtype="<f4").reshape(-1, 128)
        self.visibility = np.zeros((len(route.camera_trace), len(route.points)), np.uint8)
        for point, views in enumerate(route.landmark_views):
            self.visibility[list(views), point] = 1
        self.trace = np.asarray(route.camera_trace, np.float64)
        self.lengths = np.linalg.norm(np.diff(self.trace, axis=0), axis=1)
        self.cumulative = np.r_[0, np.cumsum(self.lengths)]
        fx, fy, cx, cy = route.intrinsics
        self.K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], np.float64)
        self.mask = feature_mask(route.profile)
        self.last_sequence, self.last_received, self.confirmations = 0, None, 0
        self.last_source_sha = None
        self.recent_confirmed_sources = []
        self.previous, self.retired = None, False

    def _fresh(self, frame):
        now = self.clock()
        return finite(now, 0, float("inf")) and 0 <= now-frame.received_at <= .25

    def _features(self, frame):
        return extract_features(frame, self.mask)

    def _solve(self, pixels, descriptors):
        cv, np = self.cv, self.np
        if len(pixels) < 24:
            return None
        # Coarse votes only select covisible reference neighborhoods. Ambiguous
        # repeated descriptors cannot directly become pose correspondences.
        coarse = cv.BFMatcher(cv.NORM_L2).knnMatch(descriptors, self.descriptors, k=4)
        votes = np.zeros(len(self.trace), np.float64)
        for pairs in coarse:
            if not pairs:
                continue
            plausible = [m for m in pairs if m.distance < .7 and m.distance <= pairs[0].distance*1.2+1e-5]
            for match in plausible:
                votes += self.visibility[:, match.trainIdx]*(1-match.distance)/len(plausible)
        candidates = []
        for _ in range(self.candidate_limit):
            at = int(np.argmax(votes))
            if votes[at] < 12:
                break
            candidates.append(at)
            votes[max(0, at-3):at+4] = 0
        # Repeated facades can crowd the correct neighborhood out of the global
        # vote shortlist. A fresh, already confirmed pose adds one candidate;
        # it still needs current-image PnP and competes with global hypotheses.
        recent = self._recent_reference_candidate()
        if recent is not None and all(abs(recent-at)>1 for at in candidates):
            candidates.append(recent)
        proposals = []
        for at in candidates:
            indices = np.flatnonzero(np.any(self.visibility[max(0, at-1):at+2], axis=0))
            proposal = self._solve_subset(pixels, descriptors, indices)
            if proposal is not None:
                proposals.append(proposal)
        if not proposals:
            return None
        return self._rank_proposals(proposals)

    def _recent_reference_candidate(self):
        if self.previous is None or self.confirmations<3 or self.last_received is None:
            return None
        dt=self.last_received-self.previous[3]
        if not 0<dt<=.5:
            return None
        nearest=self._nearest(self.previous[0])
        return None if nearest is None else nearest[0]

    def _rank_proposals(self, proposals):
        """Disambiguate verified aliases only with an already confirmed fresh pose.

        This reuses the same motion envelope enforced after solving. It never
        makes weak PnP correspondences valid, predicts a pose, or crosses a gap.
        """
        np=self.np
        proposals.sort(key=lambda p: -p[2])
        if self.previous is not None and self.confirmations>=3 and self.last_received is not None:
            old_center,old_rotation,old_progress,old_time=self.previous
            dt=self.last_received-old_time
            if 0<dt<=.5:
                limit=float(np.median(self.lengths)*5)*max(dt,.2)
                consistent=[]
                for proposal in proposals:
                    center,rotation,count=proposal[:3]
                    angle=float(np.arccos(np.clip((np.trace(rotation@old_rotation.T)-1)/2,-1,1)))
                    nearest=self._nearest(center)
                    if (count>=.75*proposals[0][2] and nearest is not None
                            and np.linalg.norm(center-old_center)<=limit and angle<=1.05
                            and abs(nearest[1]-old_progress)<=limit):
                        consistent.append(proposal)
                if consistent:
                    proposals=consistent
        best = proposals[0]
        for other in proposals[1:]:
            if self._competing_pose(best, other):
                return None
        return best

    def _competing_pose(self, best, other):
        """Reject similarly supported, materially different pose hypotheses."""
        np = self.np
        if other[2] < .75*best[2]:
            return False
        angle = float(np.arccos(np.clip((np.trace(other[1] @ best[1].T)-1)/2, -1, 1)))
        return (np.linalg.norm(other[0]-best[0]) > np.median(self.lengths)*2
                or angle > 1.05)

    def _solve_subset(self, pixels, descriptors, indices):
        cv = self.cv
        if len(indices) < 24:
            return None
        pairs = cv.BFMatcher(cv.NORM_L2).knnMatch(descriptors, self.descriptors[indices], k=2)
        matches = [a for pair in pairs if len(pair) == 2 for a, b in [pair]
                   if a.distance < .75*b.distance and a.distance < .7]
        matches = list({m.trainIdx: m for m in sorted(matches, key=lambda m: m.distance, reverse=True)}.values())
        if len(matches) < 24:
            return None
        ids = indices[[m.trainIdx for m in matches]]
        world = self.xyz[ids]
        image = pixels[[m.queryIdx for m in matches]]
        verified = self._verify_correspondences(world, image)
        if verified is None:
            return None
        center, rotation, count, error, mask = verified
        # Retain only verified 2D -> existing 3D correspondences. A temporal
        # diagnostic may track these, but must run the same PnP checks again.
        return center, rotation, count, error, ids[mask], image[mask]

    def _verify_correspondences(self, world, image):
        cv, np = self.cv, self.np
        if len(world) < 24 or len(world) != len(image):
            return None
        if not np.isfinite(world).all() or not np.isfinite(image).all():
            return None
        singular = np.linalg.svd(world-world.mean(axis=0), compute_uv=False)
        if singular[0] <= 0 or singular[2]/singular[0] < 1e-4:
            return None  # Repeated/planar structure is insufficient for this experiment.
        ok, rvec, tvec, inliers = cv.solvePnPRansac(world, image, self.K, None,
            iterationsCount=300, reprojectionError=3, confidence=.999, flags=cv.SOLVEPNP_EPNP)
        if not ok or inliers is None or len(inliers) < 20:
            return None
        keep = inliers[:, 0]
        rvec, tvec = cv.solvePnPRefineLM(world[keep], image[keep], self.K, None, rvec, tvec)
        rotation = cv.Rodrigues(rvec)[0]
        center = (-rotation.T @ tvec).reshape(3)
        projected = cv.projectPoints(world, rvec, tvec, self.K, None)[0].reshape(-1, 2)
        error = np.linalg.norm(projected-image, axis=1)
        depth = (world@rotation.T+tvec.reshape(3))[:, 2]
        mask = (error <= 3) & (depth > 1e-5)
        if (not np.isfinite(center).all() or not np.isfinite(rotation).all()
                or int(mask.sum()) < 20 or mask.mean() < .5 or not inlier_spatial_support(image[mask])
                or float(np.median(error[mask])) > 2):
            return None
        return center, rotation, int(mask.sum()), float(np.median(error[mask])), mask

    def _nearest(self, center):
        np = self.np
        directions = np.diff(self.trace, axis=0)
        fractions = np.clip(np.sum((center-self.trace[:-1])*directions, axis=1)/self.lengths**2, 0, 1)
        nearest = self.trace[:-1]+fractions[:, None]*directions
        distances = np.linalg.norm(nearest-center, axis=1)
        order = np.argsort(distances)
        at = int(order[0])
        if self.route.source_seconds[at+1]-self.route.source_seconds[at] > MAX_REFERENCE_INTERVAL_SECONDS:
            return None
        # A crossing/repeated passage has multiple route-progress interpretations.
        for other in order[1:]:
            other_progress=float(self.cumulative[other]+fractions[other]*self.lengths[other])
            at_progress=float(self.cumulative[at]+fractions[at]*self.lengths[at])
            if (abs(int(other)-at)>2 and abs(other_progress-at_progress)>float(np.median(self.lengths)*2)
                    and distances[other] <= distances[at]+self.lengths.mean()*.15):
                return None
        return at, float(self.cumulative[at]+fractions[at]*self.lengths[at]), float(distances[at])

    def _project(self, center, rotation, segment):
        # Only a local contiguous visible part. No line across behind-camera,
        # offscreen or unobserved sections, and no fabricated ground surface.
        output = []
        for index in range(segment+1, min(segment+9, len(self.trace))):
            if self.route.source_seconds[index]-self.route.source_seconds[index-1] > MAX_REFERENCE_INTERVAL_SECONDS:
                break
            world = self.trace[index]
            point = rotation@(world-center)
            if point[2] <= 1e-4:
                if output:
                    break
                continue
            xy = self.K@point
            x, y = xy[:2]/xy[2]
            if not (0 <= x < SIZE[0] and 0 <= y < SIZE[1]):
                if output:
                    break
                continue
            output.append((float(x), float(y)))
        return tuple(output)

    def observe(self, frame, *, episode_id, goal_revision, scene):
        if type(frame) is not PolicyFrame or type(scene) is not str or scene not in {"active", "menu", "unknown", "disconnected"}:
            raise ProtocolError("invalid_route_localization_observation")
        source_sha = hashlib.sha256(frame.rgb24).hexdigest()

        def result(reason, *, state="unknown", **values):
            if state == "unknown":
                self.confirmations, self.previous = 0, None
                self.recent_confirmed_sources.clear()
            return RoutePose(state, reason, self.route.id, self.route.world_revision, frame.capture_epoch,
                             frame.receiver_sequence, frame.received_at, self.clock(), source_sha,
                             (frame.width, frame.height), **values)

        if (self.retired or frame.capture_epoch != self.epoch or episode_id != self.episode
                or goal_revision != self.goal or scene == "disconnected"
                or frame.receiver_sequence <= self.last_sequence
                or self.last_received is not None and frame.received_at <= self.last_received):
            self.retired = True
            return result("route_binding_retired")
        gap = self.last_received is not None and frame.received_at-self.last_received > .5
        self.last_sequence, self.last_received = frame.receiver_sequence, frame.received_at
        duplicate_rgb = source_sha == self.last_source_sha or source_sha in self.recent_confirmed_sources
        self.last_source_sha = source_sha
        if gap:
            return result("route_observation_gap")
        if (scene != "active" or (frame.width, frame.height) != (self.route.profile.width, self.route.profile.height)
                or not self._fresh(frame)):
            return result("route_scene_geometry_or_age_unqualified")
        # A fresh delivery sequence is not proof of a fresh image. Exact RGB
        # repeats cannot independently confirm a pose; changes in overlays or
        # video noise can still hide a frozen world and require separate checks.
        if duplicate_rgb:
            return result("route_repeated_rgb_not_independent")
        solved = self._solve(*self._features(frame))
        if not self._fresh(frame):
            return result("route_frame_expired_during_localization")
        if solved is None:
            return result("route_pose_not_verified")
        center, rotation, inliers, error = solved[:4]
        nearest = self._nearest(center)
        if nearest is None:
            return result("route_progress_ambiguous")
        segment, progress, distance = nearest
        # Scale-relative submap corridor, not a guarantee of a two-metre radius.
        corridor = float(self.np.median(self.lengths)*5)
        if distance > corridor:
            return result("route_outside_observed_corridor")
        if self.previous is not None:
            old_center, old_rotation, old_progress, old_time = self.previous
            dt = frame.received_at-old_time
            turn = float(self.np.arccos(self.np.clip((self.np.trace(rotation@old_rotation.T)-1)/2, -1, 1)))
            if (self.np.linalg.norm(center-old_center) > corridor*max(dt, .2)
                    or abs(progress-old_progress) > corridor*max(dt, .2) or turn > 1.05):
                return result("route_pose_discontinuity")
        projected = self._project(center, rotation, segment)
        if not self._fresh(frame):
            return result("route_frame_expired_during_localization")
        self.previous = center, rotation, progress, frame.received_at
        self.recent_confirmed_sources = (self.recent_confirmed_sources + [source_sha])[-3:]
        self.confirmations += 1
        state = "localized" if self.confirmations >= 3 else "confirming"
        return result("relative_camera_pose_not_clearance_or_arrival", state=state,
            center=tuple(float(v) for v in center), rotation=tuple(float(v) for v in rotation.flat),
            segment=segment, progress_units=progress, cross_track_units=distance,
            inliers=inliers, median_error_px=error,
            polyline_px=projected if state == "localized" else ())


def render_guidance(frame, pose, *, clock=time.monotonic):
    """Diagnostic RGB copy only. Cannot be used as a physical-policy permit."""
    import cv2 as cv
    import numpy as np

    now = clock()
    if (type(frame) is not PolicyFrame or type(pose) is not RoutePose or pose.state != "localized"
            or pose.capture_epoch != frame.capture_epoch or pose.receiver_sequence != frame.receiver_sequence
            or pose.geometry != (frame.width, frame.height)
            or pose.received_at != frame.received_at or not finite(now, 0, float("inf"))
            or not 0 <= now-frame.received_at <= .25 or not frame.received_at <= pose.completed_at <= now
            or hashlib.sha256(frame.rgb24).hexdigest() != pose.source_rgb_sha256):
        raise ProtocolError("route_overlay_not_bound_to_fresh_rgb")
    rgb = np.frombuffer(frame.rgb24, np.uint8).reshape(frame.height, frame.width, 3).copy()
    if pose.polyline_px:
        points = np.rint(np.asarray(pose.polyline_px)*[frame.width/SIZE[0], frame.height/SIZE[1]]).astype(np.int32)
        if len(points) > 1:
            cv.polylines(rgb, [points], False, (0, 255, 255), max(2, frame.width//320))
        cv.circle(rgb, tuple(points[-1]), max(4, frame.width//160), (255, 128, 0), -1)
    return rgb.tobytes()
