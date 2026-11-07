"""Bounded, candidate-independent image-pair evidence for offline SfM review.

This helper never qualifies a route, fits a candidate pose, reads native fitted
observations, or changes a runtime default. One measurement bundle must be reused
for every candidate. Its 2D F/H filters are fitted to fresh mutual ORB matches,
not to any candidate's cameras. All mutual matches are reported as well.

The caller owns the CPU/memory-limited worker and supplies fresh resource checks.
The shared budget checks time before/after native operations; it cannot interrupt
a native call itself. No I/O, subprocess, model download, or device input exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

MAX_PAIRS = 32
MAX_VIEWS = 48
MAX_SOURCE_VIEWS = 256
MAX_IMAGE_PIXELS = 1920 * 1080
MAX_FRAME_BYTES = 128 * 1024**2
FAMILY = "fresh_masked_orb_mutual075_measurement_f_h_v1"
RANSAC_SEED = 17


@dataclass(frozen=True)
class PairSpec:
    first: str
    second: str
    first_seconds: float
    second_seconds: float


@dataclass(frozen=True)
class Camera:
    """Explicit native COLMAP pinhole calibration and camera-to-world matrix.

    ``model`` is required: a geometry JSON's fx/fy alone does not prove its
    source camera had no distortion. Distorted/unknown models are inconclusive.
    """

    model: str
    width: int
    height: int
    calibration: tuple
    camera_to_world: tuple
    distortion: tuple = ()


@dataclass(frozen=True)
class PairMeasurement:
    spec: PairSpec
    # OpenCV integer-center coordinates, immutable rows (x1, y1, x2, y2).
    matches: tuple
    fundamental_inliers: tuple
    homography_inliers: tuple
    feature_counts: tuple
    physical_duplicate_matches: int = 0


@dataclass(frozen=True)
class PairBundle:
    width: int
    height: int
    pairs: tuple[PairMeasurement, ...]
    gray_sha256: tuple
    mask_sha256: str
    recipe: tuple
    sha256: str


@dataclass
class Budget:
    checkpoint: Callable[[], None]
    max_seconds: float = 90.0
    clock: Callable[[], float] = time.monotonic
    _started: float = field(init=False)
    _last: float = field(init=False)

    def __post_init__(self):
        if (
            not callable(self.checkpoint)
            or not callable(self.clock)
            or type(self.max_seconds) not in (int, float)
            or not math.isfinite(self.max_seconds)
            or not 0 < self.max_seconds <= 90
        ):
            raise ValueError("pair_validation_budget")
        self._started = self._last = self.clock()
        if not math.isfinite(self._started):
            raise ValueError("pair_validation_clock")

    def check(self):
        for external in (False, True):
            if external:
                self.checkpoint()
            now = self.clock()
            if not math.isfinite(now) or now < self._last:
                raise RuntimeError("pair_validation_clock_regressed")
            self._last = now
            if now - self._started > self.max_seconds:
                raise RuntimeError("pair_validation_time_quota")


def _name(name):
    return (
        isinstance(name, str)
        and 0 < len(name) <= 128
        and name not in {".", ".."}
        and not any(c in name for c in "/\\:\0")
    )


def _spec(spec):
    if (
        type(spec) is not PairSpec
        or not _name(spec.first)
        or not _name(spec.second)
        or spec.first == spec.second
        or any(
            type(v) not in (int, float) or not math.isfinite(v)
            for v in (spec.first_seconds, spec.second_seconds)
        )
        or not 0 <= spec.first_seconds < spec.second_seconds <= 600
    ):
        raise ValueError("pair_validation_spec")


def sample_pairs(source_views, *, max_pairs=MAX_PAIRS):
    """Time-uniform anchors, each with adjacent/two-step neighbors, no candidate.

    Input is ordered ``(image_name, source_seconds)``. At most sixteen anchors
    use at most 48 original views. Irregular time spacing can reduce the count;
    no winner-dependent region or hand-picked timestamp is added.
    """
    import numpy as np

    if (
        type(max_pairs) is not int
        or not 1 <= max_pairs <= MAX_PAIRS
        or not 2 <= len(source_views) <= MAX_SOURCE_VIEWS
    ):
        raise ValueError("pair_validation_sampling_quota")
    names, seconds = zip(*source_views)
    if (
        len(set(names)) != len(names)
        or not all(_name(n) for n in names)
        or any(
            type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t <= 600
            for t in seconds
        )
        or any(a >= b for a, b in zip(seconds, seconds[1:]))
    ):
        raise ValueError("pair_validation_source_clock")
    if len(names) == 2:
        return (PairSpec(names[0], names[1], seconds[0], seconds[1]),)
    anchors = min(len(names) - 2, (max_pairs + 1) // 2)
    chosen = sorted(
        {
            min(range(len(names) - 2), key=lambda i: (abs(seconds[i] - t), i))
            for t in np.linspace(seconds[0], seconds[-3], anchors)
        }
    )
    result = []
    for index in chosen:
        for lag in (1, 2):
            if len(result) < max_pairs:
                result.append(
                    PairSpec(names[index], names[index + lag], seconds[index], seconds[index + lag])
                )
    return tuple(result)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _seal(width, height, pairs, gray_sha256, mask_sha256, recipe):
    from dataclasses import asdict

    payload = dict(
        width=width,
        height=height,
        pairs=[asdict(p) for p in pairs],
        gray_sha256=gray_sha256,
        mask_sha256=mask_sha256,
        recipe=recipe,
    )
    return PairBundle(
        width,
        height,
        tuple(pairs),
        tuple(gray_sha256),
        mask_sha256,
        tuple(recipe),
        _digest(payload),
    )


def _validate_bundle(bundle):
    import numpy as np

    if (
        type(bundle) is not PairBundle
        or type(bundle.width) is not int
        or type(bundle.height) is not int
        or min(bundle.width, bundle.height) < 32
        or max(bundle.width, bundle.height) > 1920
        or bundle.width * bundle.height > MAX_IMAGE_PIXELS
        or type(bundle.pairs) is not tuple
        or type(bundle.gray_sha256) is not tuple
        or type(bundle.recipe) is not tuple
        or not 1 <= len(bundle.pairs) <= MAX_PAIRS
        or len(bundle.recipe) > 16
    ):
        raise ValueError("pair_validation_bundle")
    names, times, identities = set(), {}, set()
    for measured in bundle.pairs:
        if type(measured) is not PairMeasurement:
            raise ValueError("pair_validation_measurements")
        _spec(measured.spec)
        spec = measured.spec
        if (spec.first, spec.second) in identities:
            raise ValueError("pair_validation_duplicate_pair")
        identities.add((spec.first, spec.second))
        for name, seconds in ((spec.first, spec.first_seconds), (spec.second, spec.second_seconds)):
            if name in times and times[name] != seconds:
                raise ValueError("pair_validation_source_clock")
            times[name] = seconds
            names.add(name)
        if (
            type(measured.matches) is not tuple
            or type(measured.fundamental_inliers) is not tuple
            or type(measured.homography_inliers) is not tuple
            or type(measured.feature_counts) is not tuple
            or len(measured.matches) > 4000
            or any(
                type(row) is not tuple
                or len(row) != 4
                or any(type(v) not in (int, float) for v in row)
                for row in measured.matches
            )
        ):
            raise ValueError("pair_validation_measurement_quota")
        xy = np.asarray(measured.matches, np.float64).reshape(-1, 4)
        if (
            len(measured.fundamental_inliers) != len(xy)
            or len(measured.homography_inliers) != len(xy)
            or any(
                type(v) is not bool
                for v in (*measured.fundamental_inliers, *measured.homography_inliers)
            )
            or len(measured.feature_counts) != 2
            or any(type(v) is not int or not len(xy) <= v <= 4000 for v in measured.feature_counts)
            or not np.isfinite(xy).all()
            or (xy < 0).any()
            or (xy[:, (0, 2)] >= bundle.width).any()
            or (xy[:, (1, 3)] >= bundle.height).any()
        ):
            raise ValueError("pair_validation_measurements")
        if type(
            measured.physical_duplicate_matches
        ) is not int or not 0 <= measured.physical_duplicate_matches <= len(xy):
            raise ValueError("pair_validation_measurements")
    if (
        len(names) > MAX_VIEWS
        or len(bundle.gray_sha256) != len(names)
        or any(type(row) is not tuple or len(row) != 2 for row in bundle.gray_sha256)
        or dict(bundle.gray_sha256).keys() != names
        or any(
            type(row) is not tuple
            or len(row) != 2
            or not isinstance(row[0], str)
            or type(row[1]) not in (str, int, float, bool)
            for row in bundle.recipe
        )
        or len(dict(bundle.recipe)) != len(bundle.recipe)
    ):
        raise ValueError("pair_validation_frame_selection")
    hashes = [bundle.mask_sha256, *(v for _, v in bundle.gray_sha256)]
    if any(
        not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h)
        for h in hashes
    ):
        raise ValueError("pair_validation_hash")
    expected = _seal(
        bundle.width,
        bundle.height,
        bundle.pairs,
        bundle.gray_sha256,
        bundle.mask_sha256,
        bundle.recipe,
    )
    if expected.sha256 != bundle.sha256 or dict(bundle.recipe).get("family") != FAMILY:
        raise ValueError("pair_validation_bundle_changed")
    return names


def measure_pairs(frames: Mapping, pairs, mask, *, budget: Budget, world_features=4000):
    """Detect once per selected gray image; no candidate/native observation input.

    Images must be uint8, the same bounded size and explicitly selected by
    source time. The supplied binary mask is shared by all candidates. ORB
    masks centers only: the caller must exclude the full 31-pixel descriptor
    footprint at every pyramid scale near HUD/object boundaries. That property
    is not proven here. OpenCV RNG is reset in the caller's owned offline
    worker; do not measure concurrently in a shared live CV process.
    """
    import cv2 as cv
    import numpy as np

    budget.check()
    if (
        type(world_features) is not int
        or not 64 <= world_features <= 4000
        or not 1 <= len(pairs) <= MAX_PAIRS
    ):
        raise ValueError("pair_validation_measurement_quota")
    for spec in pairs:
        _spec(spec)
    if len({(p.first, p.second) for p in pairs}) != len(pairs):
        raise ValueError("pair_validation_duplicate_pair")
    names = sorted({n for p in pairs for n in (p.first, p.second)})
    if not 2 <= len(names) <= MAX_VIEWS or set(frames) != set(names):
        raise ValueError("pair_validation_frame_selection")
    if any(
        not isinstance(frames[n], np.ndarray) or frames[n].dtype != np.uint8 or frames[n].ndim != 2
        for n in names
    ):
        raise ValueError("pair_validation_gray_image")
    height, width = frames[names[0]].shape
    if (
        min(width, height) < 32
        or max(width, height) > 1920
        or width * height > MAX_IMAGE_PIXELS
        or any(frames[n].shape != (height, width) for n in names)
        or sum(frames[n].nbytes for n in names) > MAX_FRAME_BYTES
        or not isinstance(mask, np.ndarray)
        or mask.dtype != np.uint8
        or mask.shape != (height, width)
        or not np.isin(mask, (0, 255)).all()
    ):
        raise ValueError("pair_validation_image_or_mask_quota")
    recipe = (
        ("family", FAMILY),
        ("detector_features", 10000),
        ("opencv_version", cv.__version__),
        ("detector_parameters", "scale1.2_levels8_fast10_harris_wta2_patch31_edge31"),
        ("world_features", world_features),
        ("ratio_both_directions", 0.75),
        ("independent_f_threshold_px", 1.5),
        ("independent_h_threshold_px", 3.0),
        ("ransac_max_iterations", 1000),
        ("ransac_seed", RANSAC_SEED),
        ("mask_support", "caller_excludes_full_scaled_31px_patch; not_verified_here"),
        ("pixel_coordinates", "opencv_integer_centers_v1"),
    )
    features, hashes = {}, []
    orb = cv.ORB_create(
        nfeatures=10000,
        scaleFactor=1.2,
        nlevels=8,
        fastThreshold=10,
        WTA_K=2,
        scoreType=cv.ORB_HARRIS_SCORE,
        patchSize=31,
        edgeThreshold=31,
    )
    for name in names:
        budget.check()
        gray = frames[name]
        hashes.append((name, hashlib.sha256(gray.tobytes()).hexdigest()))
        points, descriptors = orb.detectAndCompute(gray, mask)
        if descriptors is None:
            features[name] = (np.empty((0, 2), np.float64), np.empty((0, 32), np.uint8))
        else:
            strongest = sorted(range(len(points)), key=lambda i: (-points[i].response, i))[
                :world_features
            ]
            features[name] = (
                np.asarray([points[i].pt for i in strongest], np.float64),
                descriptors[strongest],
            )
        budget.check()
    measured = []
    for spec in pairs:
        budget.check()
        first, da = features[spec.first]
        second, db = features[spec.second]
        xy = np.empty((0, 4), np.float64)
        if min(len(da), len(db)) >= 2:
            matcher = cv.BFMatcher(cv.NORM_HAMMING)
            forward, backward = matcher.knnMatch(da, db, k=2), matcher.knnMatch(db, da, k=2)
            reverse = {
                p[0].queryIdx: p[0].trainIdx
                for p in backward
                if len(p) == 2 and p[0].distance < 0.75 * p[1].distance
            }
            matches = [
                p[0]
                for p in forward
                if len(p) == 2
                and p[0].distance < 0.75 * p[1].distance
                and reverse.get(p[0].trainIdx) == p[0].queryIdx
            ]
            if matches:
                xy = np.asarray([(*first[m.queryIdx], *second[m.trainIdx]) for m in matches])
        fmask = hmask = np.zeros(len(xy), bool)
        unique, seen_first, seen_second = [], set(), set()
        for index, row in enumerate(xy):
            a, b = row[:2].tobytes(), row[2:].tobytes()
            if a not in seen_first and b not in seen_second:
                unique.append(index)
                seen_first.add(a)
                seen_second.add(b)
        if len(unique) >= 8:
            fit = xy[unique]
            cv.setRNGSeed(RANSAC_SEED)
            _, fm = cv.findFundamentalMat(fit[:, :2], fit[:, 2:], cv.USAC_MAGSAC, 1.5, 0.999, 1000)
            cv.setRNGSeed(RANSAC_SEED)
            _, hm = cv.findHomography(
                fit[:, :2], fit[:, 2:], cv.RANSAC, 3.0, maxIters=1000, confidence=0.999
            )
            fmask, hmask = np.zeros(len(xy), bool), np.zeros(len(xy), bool)
            if fm is not None:
                fmask[unique] = fm.ravel().astype(bool)
            if hm is not None:
                hmask[unique] = hm.ravel().astype(bool)
        measured.append(
            PairMeasurement(
                spec,
                tuple(tuple(map(float, row)) for row in xy),
                tuple(map(bool, fmask)),
                tuple(map(bool, hmask)),
                (len(first), len(second)),
                len(xy) - len(unique),
            )
        )
        budget.check()
    result = _seal(
        width, height, measured, hashes, hashlib.sha256(mask.tobytes()).hexdigest(), recipe
    )
    _validate_bundle(result)
    budget.check()
    return result


def _stats(values):
    import numpy as np

    values = np.asarray(values, np.float64)
    if not len(values):
        return dict(count=0, median=None, mean=None, p95=None, maximum=None)
    if not np.isfinite(values).all():
        raise ValueError("pair_validation_nonfinite_residual")
    return dict(
        count=len(values),
        median=float(np.median(values)),
        mean=float(np.mean(values)),
        p95=float(np.percentile(values, 95)),
        maximum=float(np.max(values)),
    )


def _camera(camera, size):
    import numpy as np

    from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv

    if type(camera) is not Camera:
        raise ValueError("invalid_camera_contract")
    if camera.model not in {"SIMPLE_PINHOLE", "PINHOLE"} or camera.distortion:
        raise ValueError("unsupported_calibration_model")
    if (
        type(camera.width) is not int
        or type(camera.height) is not int
        or min(camera.width, camera.height) < 1
        or camera.width * size[1] != camera.height * size[0]
    ):
        raise ValueError("unsupported_calibration_geometry")
    matrix = np.asarray(camera.camera_to_world, np.float64)
    calibration = np.asarray(camera.calibration, np.float64)
    if (
        matrix.shape != (3, 4)
        or not np.isfinite(matrix).all()
        or (np.abs(matrix) > 1e12).any()
        or calibration.shape != (3, 3)
        or calibration[0, 1] != 0
        or calibration[1, 0] != 0
        or not np.allclose(matrix[:, :3].T @ matrix[:, :3], np.eye(3), atol=1e-6, rtol=0)
        or not math.isclose(float(np.linalg.det(matrix[:, :3])), 1, abs_tol=1e-6)
    ):
        raise ValueError("invalid_camera_pose_or_calibration")
    k = colmap_calibration_to_opencv(calibration, (camera.width, camera.height), size)
    return matrix[:, :3].T, -matrix[:, :3].T @ matrix[:, 3], matrix[:, 3], k


def _rotation_transfer(xy, rotation, first_k, second_k):
    import numpy as np

    homography = second_k @ rotation @ np.linalg.inv(first_k)
    a, b = np.c_[xy[:, :2], np.ones(len(xy))], np.c_[xy[:, 2:], np.ones(len(xy))]
    predicted = a @ homography.T
    finite = np.isfinite(predicted).all(axis=1) & (predicted[:, 2] > 1e-12)
    return _stats(
        np.linalg.norm(predicted[finite, :2] / predicted[finite, 2, None] - b[finite, :2], axis=1)
    )


def _norm(vector):
    import numpy as np

    maximum = float(np.max(np.abs(vector)))
    return maximum * float(np.linalg.norm(vector / maximum)) if maximum else 0.0


def _pair_error(xy, first, second, scene_span):
    import numpy as np

    ra, ta, _, ka = first
    rb, tb, _, kb = second
    rotation = rb @ ra.T
    translation = tb - rotation @ ta
    length = _norm(translation)
    result = dict(rotation_only_transfer_px=_rotation_transfer(xy, rotation, ka, kb))
    if not math.isfinite(length) or length <= scene_span * 1e-9 or length == 0:
        return dict(result, status="unobservable_translation", symmetric_epipolar_rms_px=_stats([]))
    x, y, z = translation / length
    skew = np.asarray([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    fundamental = np.linalg.inv(kb).T @ skew @ rotation @ np.linalg.inv(ka)
    a, b = np.c_[xy[:, :2], np.ones(len(xy))], np.c_[xy[:, 2:], np.ones(len(xy))]
    line_b, line_a = a @ fundamental.T, b @ fundamental
    numerator = np.abs(np.einsum("ij,ij->i", b, line_b))
    norm_a, norm_b = np.linalg.norm(line_a[:, :2], axis=1), np.linalg.norm(line_b[:, :2], axis=1)
    if (norm_a <= 1e-15).any() or (norm_b <= 1e-15).any():
        return dict(
            result, status="degenerate_epipolar_lines", symmetric_epipolar_rms_px=_stats([])
        )
    d1, d2 = numerator / norm_a, numerator / norm_b
    return dict(
        result,
        status="evaluated",
        first_line_distance_px=_stats(d1),
        second_line_distance_px=_stats(d2),
        symmetric_epipolar_rms_px=_stats(np.sqrt((d1 * d1 + d2 * d2) / 2)),
    )


def evaluate_candidate(bundle: PairBundle, cameras: Mapping, *, budget: Budget):
    """Evaluate fixed pinhole poses against exactly the same pair bundle.

    Homography dominance is a warning, not an automatic planar-scene veto.
    Cheirality or a larger model-derived parallax is not an acceptance signal.
    Unsupported distortion remains inconclusive; raw distorted F is never used.
    """
    import numpy as np

    budget.check()
    names = _validate_bundle(bundle)
    if len(names) > MAX_VIEWS or len(cameras) > MAX_SOURCE_VIEWS:
        raise ValueError("pair_validation_camera_quota")
    parsed, failures = {}, {}
    for name in sorted(names):
        budget.check()
        if name not in cameras:
            failures[name] = "missing_camera"
            continue
        try:
            parsed[name] = _camera(cameras[name], (bundle.width, bundle.height))
        except (ValueError, TypeError, IndexError) as error:
            failures[name] = str(error)
    centers = np.asarray([row[2] for row in parsed.values()])
    span = _norm(np.ptp(centers, axis=0)) if len(centers) >= 2 else 0.0
    rows, raw_medians, filtered_medians = [], [], []
    for measured in bundle.pairs:
        budget.check()
        spec = measured.spec
        xy = np.asarray(measured.matches, np.float64).reshape(-1, 4)
        fmask = np.asarray(measured.fundamental_inliers, bool)
        hmask = np.asarray(measured.homography_inliers, bool)
        if (
            len(xy) > 4000
            or len(fmask) != len(xy)
            or len(hmask) != len(xy)
            or not np.isfinite(xy).all()
        ):
            raise ValueError("pair_validation_measurements")
        row = dict(
            first=spec.first,
            second=spec.second,
            first_seconds=spec.first_seconds,
            second_seconds=spec.second_seconds,
            mutual_matches=len(xy),
            independent_f_inliers=int(fmask.sum()),
            physical_duplicates_excluded_from_2d_fit=measured.physical_duplicate_matches,
            homography_inlier_fraction=float(hmask.mean()) if len(hmask) else None,
            planar_or_rotation_possible=bool(len(hmask) and hmask.mean() > 0.85),
        )
        if spec.first in failures or spec.second in failures:
            rows.append(
                dict(
                    row,
                    status="inconclusive_camera",
                    camera_reasons={
                        n: failures[n] for n in (spec.first, spec.second) if n in failures
                    },
                )
            )
            continue
        if len(xy) < 8:
            rows.append(dict(row, status="insufficient_matches"))
            continue
        raw = _pair_error(xy, parsed[spec.first], parsed[spec.second], span)
        filtered = _pair_error(xy[fmask], parsed[spec.first], parsed[spec.second], span)
        rows.append(
            dict(row, status=raw["status"], all_mutual=raw, independent_2d_inliers=filtered)
        )
        if raw["status"] == "evaluated":
            raw_medians.append(raw["symmetric_epipolar_rms_px"]["median"])
        if filtered["status"] == "evaluated" and int(fmask.sum()) >= 24:
            filtered_medians.append(filtered["symmetric_epipolar_rms_px"]["median"])
        budget.check()
    return dict(
        schema="sphere-independent-pair-candidate-evidence-v1",
        family=FAMILY,
        measurement_sha256=bundle.sha256,
        image_size=[bundle.width, bundle.height],
        pair_count=len(rows),
        camera_failures=failures,
        pairs=rows,
        all_mutual_pair_medians_px=_stats(raw_medians),
        independent_2d_pair_medians_px=_stats(filtered_medians),
        incomplete=bool(failures),
        candidate_poses_modified=False,
        candidate_observations_used_for_filter=False,
        pair_selection="explicit shared source pairs; sample_pairs supplies a deterministic time-only plan",
        mask_descriptor_footprint_verified=False,
        execution_qualified=False,
        navigation_qualified=False,
        admission_effect="none; comparative diagnostic only",
        physical_actions=0,
        limitations=[
            "Fresh descriptors/associations are not native fitted observations, but may depict the same physical features.",
            "A shared 2D filter may still retain repeated textures or moving objects; all mutual matches remain reported.",
            "Epipolar consistency alone does not establish scale, full geometry, static surfaces or navigation readiness.",
        ],
    )


def compare_candidates(bundle, candidates, *, budget: Budget):
    """Paired diagnostic signal, without selecting or admitting a winner.

    A missing/unsupported camera makes the comparison inconclusive. A shared
    2D-inlier count of 24 and eight common pairs are comparability floors only;
    they do not establish full-route coverage, true geometry or navigation.
    """
    if not 2 <= len(candidates) <= 8 or not all(_name(name) for name in candidates):
        raise ValueError("pair_validation_candidate_quota")
    reports = {
        name: evaluate_candidate(bundle, cameras, budget=budget)
        for name, cameras in sorted(candidates.items())
    }
    eligible = []
    for index in range(len(bundle.pairs)):
        rows = [r["pairs"][index] for r in reports.values()]
        if all(
            row.get("independent_f_inliers", 0) >= 24
            and row.get("independent_2d_inliers", {}).get("status") == "evaluated"
            for row in rows
        ):
            eligible.append(index)
    comparisons, names = [], list(reports)
    for at, first in enumerate(names):
        for second in names[at + 1 :]:
            differences, first_lower, second_lower = [], 0, 0
            for index in eligible:
                budget.check()
                a = reports[first]["pairs"][index]["independent_2d_inliers"][
                    "symmetric_epipolar_rms_px"
                ]["median"]
                b = reports[second]["pairs"][index]["independent_2d_inliers"][
                    "symmetric_epipolar_rms_px"
                ]["median"]
                differences.append(b - a)
                first_lower += a < b
                second_lower += b < a
            comparisons.append(
                dict(
                    first=first,
                    second=second,
                    common_pairs=len(eligible),
                    first_lower_pairs=first_lower,
                    second_lower_pairs=second_lower,
                    second_minus_first_median_error_px=_stats(differences),
                )
            )
    incomplete = any(r["incomplete"] for r in reports.values())
    return dict(
        schema="sphere-independent-pair-candidate-comparison-v1",
        measurement_sha256=bundle.sha256,
        reports=reports,
        comparisons=comparisons,
        common_pair_indices=eligible,
        status="comparison_available" if len(eligible) >= 8 and not incomplete else "inconclusive",
        winner_selected=False,
        admission_effect="none",
        physical_actions=0,
        execution_qualified=False,
        navigation_qualified=False,
    )
