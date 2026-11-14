"""Measured native-reference image localization for controlled experiments.

This is a separate artifact/query family. It has no descriptor placeholders and
does not turn legacy sparse maps into qualified maps. Its image/PnP, motion and
freshness checks are the unchanged RouteLocalizer methods.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import zipfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from motor_worker.landmarks import RouteViewProfile
from motor_worker.policy import epoch_valid, finite
from motor_worker.protocol import ProtocolError, message
from motor_worker.route_localization import (
    MAX_REFERENCE_INTERVAL_SECONDS,
    MIN_TRACE_STEP_UNITS,
    PNP_VERIFICATION_POLICY,
    SIZE,
    RouteLocalizer,
    feature_mask,
    prepare_feature_gray,
)

FAMILY = "measured_native_reference_lk_v1"
REFERENCE_LK_VERIFICATION_POLICY = PNP_VERIFICATION_POLICY + ":measured_reference_lk_v1"
REFERENCE_LK_SEARCH_POLICY = "global_masked64x36_top3_measured_reference_fbLK_v1"
SCHEMA = "sphere-reference-lk-route-v1"
MAX_VIEWS = 256
MAX_PER_VIEW = 512
MAX_CACHE_BYTES = 128 * 1024**2
MAX_METADATA_BYTES = 256 * 1024
MAX_SHARED_BYTES = 256 * 1024**2
CACHE_FILE = "reference-lk.npz"
_SOURCE_SHA = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_CORE_SHA = hashlib.sha256(
    Path(__file__).with_name("route_localization.py").read_bytes()
).hexdigest()
_LOCK = threading.RLock()
_CACHES = {}
_ARRAYS = {"grays", "mask", "offsets", "native_ids", "native_rows", "pixels", "xyz"}


def canonical_hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@lru_cache(maxsize=1)
def _exporter_source_sha():
    # Legacy controller imports also load this module. Only the new family
    # requires the preparation tools, which need not ship in a worker package.
    return hashlib.sha256(
        (Path(__file__).parents[1] / "scripts/pilot/route_reference_lk_export.py").read_bytes()
    ).hexdigest()


def reference_lk_pipeline_id():
    import cv2

    return canonical_hash(
        dict(
            family=FAMILY,
            source=_SOURCE_SHA,
            core_source=_CORE_SHA,
            exporter_source=_exporter_source_sha(),
            opencv=cv2.__version__,
            size=SIZE,
            reference_quota=MAX_PER_VIEW,
            retrieval="masked64x36_normalized_gray_top3",
            flow="fb1_error12_win21_levels3",
            pnp_policy=PNP_VERIFICATION_POLICY,
            descriptor_features=False,
        )
    )


def _sha(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _asset(folder, name):
    path = folder / name
    if (
        path.is_symlink()
        or path.is_junction()
        or not path.is_file()
        or path.resolve().parent != folder.resolve()
    ):
        raise ProtocolError("reference_lk_asset_path")
    return path


class _Lease:
    def __init__(self, key, entry):
        self.key, self.entry = key, entry

    def acquire(self):
        with _LOCK:
            if self.entry is None:
                raise ProtocolError("reference_lk_cache_closed")
            self.entry["refs"] += 1
            return _Lease(self.key, self.entry)

    @property
    def arrays(self):
        if self.entry is None:
            raise ProtocolError("reference_lk_cache_closed")
        return self.entry["arrays"]

    def close(self):
        with _LOCK:
            entry, self.entry = self.entry, None
            if entry is not None:
                entry["refs"] -= 1
                if not entry["refs"]:
                    _CACHES.pop(self.key, None)
                    entry["arrays"].clear()

    def __del__(self):
        self.close()


def _cache(path, sha256, views, observations):
    import numpy as np

    if not _sha(sha256) or path.stat().st_size > MAX_CACHE_BYTES or _hash(path) != sha256:
        raise ProtocolError("reference_lk_cache_integrity")
    key = (str(path.resolve()), sha256, reference_lk_pipeline_id())
    with _LOCK:
        if key in _CACHES:
            entry = _CACHES[key]
            entry["refs"] += 1
            return _Lease(key, entry)
        expected = dict(
            grays=((views, SIZE[1], SIZE[0]), "|u1"),
            mask=((SIZE[1], SIZE[0]), "|u1"),
            offsets=((views + 1,), "<u4"),
            native_ids=((observations,), "<u8"),
            native_rows=((observations,), "<u4"),
            pixels=((observations, 2), "<f4"),
            xyz=((observations, 3), "<f8"),
        )
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) != len(_ARRAYS) or {i.filename for i in infos} != {
                n + ".npy" for n in _ARRAYS
            }:
                raise ProtocolError("reference_lk_cache_schema")
            total = 0
            for info in infos:
                if info.flag_bits & 1 or info.compress_type not in (
                    zipfile.ZIP_STORED,
                    zipfile.ZIP_DEFLATED,
                ):
                    raise ProtocolError("reference_lk_cache_schema")
                name = info.filename[:-4]
                with archive.open(info) as stream:
                    if np.lib.format.read_magic(stream) != (1, 0):
                        raise ProtocolError("reference_lk_cache_header")
                    shape, fortran, dtype = np.lib.format.read_array_header_1_0(
                        stream, max_header_size=4096
                    )
                    count = math.prod(shape) * dtype.itemsize
                    if (
                        shape != expected[name][0]
                        or dtype.str != expected[name][1]
                        or fortran
                        or info.file_size != stream.tell() + count
                    ):
                        raise ProtocolError("reference_lk_cache_header")
                    total += count
            if (
                total > MAX_CACHE_BYTES
                or total + sum(e["bytes"] for e in _CACHES.values()) > MAX_SHARED_BYTES
            ):
                raise ProtocolError("reference_lk_cache_quota")
            arrays = {}
            for name in sorted(_ARRAYS):
                with archive.open(name + ".npy") as stream:
                    value = np.load(stream, allow_pickle=False)
                    # Immutable bytes backing prevents callers re-enabling writes.
                    arrays[name] = np.frombuffer(value.tobytes(), dtype=value.dtype).reshape(
                        value.shape
                    )
        entry = dict(arrays=arrays, refs=1, bytes=total)
        _CACHES[key] = entry
        return _Lease(key, entry)


@dataclass(frozen=True)
class ReferenceLKRoute:
    id: str
    world_revision: str
    source_sha256: str
    pipeline_sha256: str
    profile: RouteViewProfile
    intrinsics: tuple
    camera_trace: tuple
    source_seconds: tuple
    reference_rgb_sha256: tuple
    source_frame_indices: tuple
    source_capture_sha256: str
    source_index_sha256: str
    source_geometry_sha256: str
    model_sha256: tuple
    reference_names: tuple
    source_png_sha256: tuple
    reference_gray_sha256: tuple
    native_row_counts: tuple
    cache_sha256: str
    observations: int
    _lease: _Lease = field(repr=False, compare=False)

    def __post_init__(self):
        import numpy as np

        n = len(self.camera_trace)
        if (
            not epoch_valid(self.id)
            or not epoch_valid(self.world_revision)
            or self.pipeline_sha256 != reference_lk_pipeline_id()
            or type(self.profile) is not RouteViewProfile
            or (self.profile.width, self.profile.height) != SIZE
            or not 2 <= n <= MAX_VIEWS
            or any(
                not _sha(v)
                for v in (
                    self.source_sha256,
                    self.source_capture_sha256,
                    self.source_index_sha256,
                    self.source_geometry_sha256,
                    self.cache_sha256,
                )
            )
            or len(self.intrinsics) != 4
            or any(not finite(v, 1, 10000) for v in self.intrinsics[:2])
            or not finite(self.intrinsics[2], 0, SIZE[0])
            or not finite(self.intrinsics[3], 0, SIZE[1])
            or any(
                len(v) != n
                for v in (
                    self.source_seconds,
                    self.reference_rgb_sha256,
                    self.source_frame_indices,
                    self.reference_names,
                    self.source_png_sha256,
                    self.reference_gray_sha256,
                    self.native_row_counts,
                )
            )
            or any(not finite(v, 0, 600) for v in self.source_seconds)
            or any(b <= a for a, b in zip(self.source_seconds, self.source_seconds[1:]))
            or any(type(v) is not int or not 0 <= v <= 72000 for v in self.source_frame_indices)
            or any(b <= a for a, b in zip(self.source_frame_indices, self.source_frame_indices[1:]))
            or any(
                not _sha(v)
                for values in (
                    self.reference_rgb_sha256,
                    self.source_png_sha256,
                    self.reference_gray_sha256,
                )
                for v in values
            )
            or len(set(self.reference_names)) != n
            or any(
                type(name) is not str
                or len(name) != 12
                or not name[:8].isdigit()
                or not name.endswith(".png")
                for name in self.reference_names
            )
            or any(
                type(count) is not int or not 24 <= count <= 2_000_000
                for count in self.native_row_counts
            )
            or len(self.model_sha256) != 5
            or dict(self.model_sha256).keys()
            != {"cameras.bin", "images.bin", "points3D.bin", "frames.bin", "rigs.bin"}
            or any(not _sha(value) for _, value in self.model_sha256)
            or type(self.observations) is not int
            or not n * 24 <= self.observations <= n * MAX_PER_VIEW
        ):
            raise ProtocolError("invalid_reference_lk_route")
        trace = np.asarray(self.camera_trace, np.float64)
        a = self._lease.arrays
        expected_source = canonical_hash(
            dict(
                source_capture_sha256=self.source_capture_sha256,
                source_index_sha256=self.source_index_sha256,
                source_geometry_sha256=self.source_geometry_sha256,
                model_sha256=dict(self.model_sha256),
            )
        )
        if (
            self.source_sha256 != expected_source
            or trace.shape != (n, 3)
            or not np.isfinite(trace).all()
            or (np.abs(trace) > 1e8).any()
            or not (np.linalg.norm(np.diff(trace, axis=0), axis=1) >= MIN_TRACE_STEP_UNITS).any()
            or not np.isin(a["mask"], (0, 255)).all()
            or not np.array_equal(a["mask"], feature_mask(self.profile))
            or a["offsets"][0] != 0
            or a["offsets"][-1] != self.observations
            or (np.diff(a["offsets"].astype(np.int64)) < 24).any()
            or (np.diff(a["offsets"].astype(np.int64)) > MAX_PER_VIEW).any()
            or not np.isfinite(a["pixels"]).all()
            or not np.isfinite(a["xyz"]).all()
            or (np.abs(a["xyz"]) > 1e8).any()
            or (a["pixels"] < 0).any()
            or (a["pixels"][:, 0] >= SIZE[0]).any()
            or (a["pixels"][:, 1] >= SIZE[1]).any()
        ):
            raise ProtocolError("reference_lk_measurements_invalid")
        first = {}
        for view in range(n):
            start, end = map(int, a["offsets"][view : view + 2])
            ids, rows = a["native_ids"][start:end], a["native_rows"][start:end]
            xy = np.minimum(np.rint(a["pixels"][start:end]).astype(int), np.array(SIZE) - 1)
            if (
                len(np.unique(ids)) != len(ids)
                or len(np.unique(rows)) != len(rows)
                or (rows >= self.native_row_counts[view]).any()
                or (a["mask"][xy[:, 1], xy[:, 0]] != 255).any()
                or hashlib.sha256(a["grays"][view].tobytes()).hexdigest()
                != self.reference_gray_sha256[view]
            ):
                raise ProtocolError("reference_lk_measured_rows_invalid")
            for at in range(start, end):
                identity = int(a["native_ids"][at])
                xyz = a["xyz"][at].tobytes()
                if identity in first and first[identity] != xyz:
                    raise ProtocolError("reference_lk_native_xyz_changed")
                first[identity] = xyz

    def acquire_cache(self):
        return self._lease.acquire()

    def close(self):
        self._lease.close()

    @classmethod
    def load(cls, path, *, sha256):
        path = Path(path)
        if (
            not _sha(sha256)
            or path.is_symlink()
            or path.is_junction()
            or not path.is_file()
            or path.stat().st_size > MAX_METADATA_BYTES
        ):
            raise ProtocolError("reference_lk_route_unavailable")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ProtocolError("reference_lk_route_integrity")
        data = message(raw.decode("utf8"), MAX_METADATA_BYTES, strict_numbers=True)
        fields = set(cls.__dataclass_fields__) - {"_lease"} | {
            "schema",
            "cache_file",
            "execution_qualified",
        }
        if (
            data.keys() != fields
            or data.pop("schema") != SCHEMA
            or data.pop("cache_file") != CACHE_FILE
            or data.pop("execution_qualified") is not False
        ):
            raise ProtocolError("reference_lk_route_schema")
        try:
            data["profile"] = RouteViewProfile.parse(
                json.dumps(dict(schema_version=1, **data["profile"]))
            )
            for name in ("camera_trace", "model_sha256"):
                data[name] = tuple(tuple(row) for row in data[name])
            for name in (
                "intrinsics",
                "source_seconds",
                "reference_rgb_sha256",
                "source_frame_indices",
                "reference_names",
                "source_png_sha256",
                "reference_gray_sha256",
                "native_row_counts",
            ):
                data[name] = tuple(data[name])
            views, observations = len(data["camera_trace"]), data["observations"]
            if (
                not 2 <= views <= MAX_VIEWS
                or type(observations) is not int
                or not views * 24 <= observations <= views * MAX_PER_VIEW
            ):
                raise ProtocolError("reference_lk_cache_quota")
            lease = _cache(
                _asset(path.parent, CACHE_FILE), data["cache_sha256"], views, observations
            )
            try:
                return cls(**data, _lease=lease)
            except BaseException:
                lease.close()
                raise
        except ProtocolError:
            raise
        except (ValueError, TypeError, KeyError, zipfile.BadZipFile) as error:
            raise ProtocolError("reference_lk_route_schema") from error


def reference_lk_support(route):
    if type(route) is not ReferenceLKRoute:
        raise ProtocolError("invalid_reference_lk_support")
    a = route._lease.arrays
    counts = [int(b - a0) for a0, b in zip(a["offsets"], a["offsets"][1:])]
    neighborhoods = []
    for at in range(len(counts)):
        start, end = int(a["offsets"][max(0, at - 1)]), int(a["offsets"][min(len(counts), at + 2)])
        neighborhoods.append(len(set(map(int, a["native_ids"][start:end]))))
    gaps = [
        dict(start_seconds=a0, end_seconds=b)
        for a0, b in zip(route.source_seconds, route.source_seconds[1:])
        if b - a0 > MAX_REFERENCE_INTERVAL_SECONDS
    ]
    return dict(
        reference_views=len(counts),
        min_correspondences_required=24,
        per_view_landmarks=counts,
        neighborhood_landmarks=neighborhoods,
        views_below_24=sum(v < 24 for v in counts),
        neighborhoods_below_24=sum(v < 24 for v in neighborhoods),
        zero_landmark_views=sum(v == 0 for v in counts),
        all_reference_neighborhoods_supported=all(v >= 24 for v in neighborhoods),
        all_reference_intervals_observed=not gaps,
        unobserved_intervals=gaps,
        reference_interval_limit_seconds=MAX_REFERENCE_INTERVAL_SECONDS,
        navigation_qualified=False,
    )


class ReferenceLKLocalizer(RouteLocalizer):
    """Strict typed-family constructor; unchanged base observation/PnP gates."""

    def __init__(
        self,
        route,
        *,
        capture_epoch,
        episode_id,
        goal_revision,
        clock=time.monotonic,
        diagnostic_partial_map=False,
        candidate_limit=3,
    ):
        import cv2 as cv
        import numpy as np

        if (
            type(route) is not ReferenceLKRoute
            or route.pipeline_sha256 != reference_lk_pipeline_id()
            or any(not epoch_valid(v) for v in (capture_epoch, episode_id, goal_revision))
            or type(diagnostic_partial_map) is not bool
            or candidate_limit != 3
            or type(candidate_limit) is not int
            or not callable(clock)
        ):
            raise ProtocolError("invalid_reference_lk_localizer_binding")
        support = reference_lk_support(route)
        if (
            not support["all_reference_neighborhoods_supported"]
            or not support["all_reference_intervals_observed"]
        ):
            raise ProtocolError("route_map_has_unobserved_sections")
        self.route, self.epoch, self.episode, self.goal, self.clock = (
            route,
            capture_epoch,
            episode_id,
            goal_revision,
            clock,
        )
        self.candidate_limit, self.cv, self.np = 3, cv, np
        self.trace = np.asarray(route.camera_trace, np.float64)
        self.lengths = np.linalg.norm(np.diff(self.trace, axis=0), axis=1)
        self.cumulative = np.r_[0, np.cumsum(self.lengths)]
        self.reference_times = np.asarray(route.source_seconds, np.float64)
        self.reference_speeds = self.lengths / np.diff(self.reference_times)
        if not np.isfinite(self.reference_speeds).all():
            raise ProtocolError("route_reference_speed_invalid")
        self.reference_times.setflags(write=False)
        self.reference_speeds.setflags(write=False)
        fx, fy, cx, cy = route.intrinsics
        self.K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]], np.float64)
        self._cache = route.acquire_cache()
        self.mask = self._cache.arrays["mask"]
        self.last_sequence, self.last_received, self.confirmations = 0, None, 0
        self.last_source_sha = None
        self.recent_confirmed_sources = []
        self.previous, self.retired, self._proposal_index = None, False, None
        self.last_diagnostic = {}
        self._tiny_mask = (
            cv.resize(self.mask, (64, 36), interpolation=cv.INTER_AREA).reshape(-1) > 250
        )
        if not self._tiny_mask.any():
            self.close()
            raise ProtocolError("reference_lk_mask_empty")
        self._tiny = np.asarray(
            [self._thumbnail(gray) for gray in self._cache.arrays["grays"]], np.float32
        )

    def _thumbnail(self, gray):
        values = (
            self.cv.resize(gray, (64, 36), interpolation=self.cv.INTER_AREA)
            .reshape(-1)[self._tiny_mask]
            .astype(self.np.float32)
        )
        return (values - values.mean()) / max(float(values.std()), 1e-3)

    def _features(self, frame):
        began = time.perf_counter()
        self._gray = prepare_feature_gray(frame)
        self.last_diagnostic["featurePreparationMs"] = (time.perf_counter() - began) * 1000
        return (), ()

    def _solve(self, *_unused):
        cv, np = self.cv, self.np
        began = time.perf_counter()
        arrays = self._cache.arrays
        scores = np.mean((self._tiny - self._thumbnail(self._gray)) ** 2, axis=1)
        rank = np.argsort(scores, kind="stable")[:3]
        self.last_diagnostic.update(
            method="measured_reference_lk",
            candidateReferenceIndices=list(map(int, rank)),
            coarseSearchMs=(time.perf_counter() - began) * 1000,
            queryFamily=FAMILY,
        )
        proposals, retained = [], []
        options = dict(
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        for at in rank:
            start, end = map(int, arrays["offsets"][at : at + 2])
            old = arrays["pixels"][start:end].reshape(-1, 1, 2)
            forward, status, error = cv.calcOpticalFlowPyrLK(
                arrays["grays"][at], self._gray, old, None, **options
            )
            if forward is None or status is None or error is None:
                retained.append(0)
                continue
            backward, back_status, _ = cv.calcOpticalFlowPyrLK(
                self._gray, arrays["grays"][at], forward, None, **options
            )
            if backward is None or back_status is None:
                retained.append(0)
                continue
            pixels = forward.reshape(-1, 2)
            finite = np.isfinite(pixels).all(axis=1)
            inside = (
                finite
                & (pixels[:, 0] >= 0)
                & (pixels[:, 0] < SIZE[0])
                & (pixels[:, 1] >= 0)
                & (pixels[:, 1] < SIZE[1])
            )
            allowed = np.zeros(len(pixels), bool)
            xy = np.minimum(np.rint(pixels[inside]).astype(int), np.array(SIZE) - 1)
            allowed[inside] = self.mask[xy[:, 1], xy[:, 0]] != 0
            delta = np.linalg.norm(backward.reshape(-1, 2) - old.reshape(-1, 2), axis=1)
            keep = (
                (status.reshape(-1) == 1)
                & (back_status.reshape(-1) == 1)
                & np.isfinite(delta)
                & (delta <= 1)
                & np.isfinite(error.reshape(-1))
                & (error.reshape(-1) <= 12)
                & allowed
            )
            retained.append(int(keep.sum()))
            if keep.sum() < 24:
                continue
            verified = self._verify_correspondences(
                arrays["xyz"][start:end][keep], pixels[keep].astype(np.float64)
            )
            if verified is not None:
                proposals.append(verified[:4])
        self.last_diagnostic.update(
            flowRetainedByCandidate=retained,
            verifiedCandidateCount=len(proposals),
            candidateMatchPnPMs=(time.perf_counter() - began) * 1000,
        )
        return self._rank_proposals(proposals) if proposals else None

    def close(self):
        self.retired = True
        cache = getattr(self, "_cache", None)
        if cache is not None:
            cache.close()
        self._gray = self._tiny = None

    def __del__(self):
        self.close()
