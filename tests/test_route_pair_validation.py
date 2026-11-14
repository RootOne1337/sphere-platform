"""A shared fresh measurement must not inherit a candidate's fitted geometry."""

from dataclasses import replace
from types import SimpleNamespace

import cv2 as cv
import numpy as np
import pytest

from scripts.pilot import route_pair_validation as validation


def budget(**kwargs):
    return validation.Budget(lambda: None, **kwargs)


def camera(center=(0.0, 0.0, 0.0), rotation=None, *, model="SIMPLE_PINHOLE"):
    rotation = np.eye(3) if rotation is None else rotation
    return validation.Camera(
        model,
        640,
        360,
        ((320.0, 0.0, 320.0), (0.0, 320.0, 180.0), (0.0, 0.0, 1.0)),
        tuple(tuple(map(float, row)) for row in np.c_[rotation, center]),
    )


def projected_fixture(pair_count=1):
    rng = np.random.default_rng(42)
    xyz = np.c_[rng.uniform(-2, 2, 160), rng.uniform(-1.2, 1.2, 160), rng.uniform(4, 12, 160)]
    cameras, pairs = {}, []
    for i in range(pair_count + 1):
        cameras[f"{i}.png"] = camera((i * 0.15, 0.0, 0.0))
    k = np.array([[320.0, 0.0, 319.5], [0.0, 320.0, 179.5], [0.0, 0.0, 1.0]])
    for i in range(pair_count):

        def project(c):
            matrix = np.asarray(c.camera_to_world)
            rays = (xyz - matrix[:, 3]) @ matrix[:, :3]
            pixels = rays @ k.T
            return pixels[:, :2] / pixels[:, 2, None]

        name_a, name_b = f"{i}.png", f"{i + 1}.png"
        xy = np.c_[project(cameras[name_a]), project(cameras[name_b])]
        pairs.append(
            validation.PairMeasurement(
                validation.PairSpec(name_a, name_b, i * 0.2, (i + 1) * 0.2),
                tuple(tuple(map(float, row)) for row in xy),
                (True,) * len(xy),
                (False,) * len(xy),
                (len(xy), len(xy)),
            )
        )
    bundle = validation._seal(
        640,
        360,
        pairs,
        tuple((name, "a" * 64) for name in sorted(cameras)),
        "b" * 64,
        (("family", validation.FAMILY),),
    )
    return bundle, cameras


def test_fixed_true_pose_beats_deformed_pose_using_identical_measurements():
    bundle, cameras = projected_fixture(8)
    bad = {
        name: replace(
            cam,
            camera_to_world=tuple(
                tuple(map(float, row))
                for row in np.c_[
                    np.eye(3), [int(name.split(".")[0]) * 0.15, int(name.split(".")[0]) * 0.09, 0.0]
                ]
            ),
        )
        for name, cam in cameras.items()
    }
    proof = validation.compare_candidates(
        bundle, {"true": cameras, "deformed": bad}, budget=budget()
    )
    true, deformed = proof["reports"]["true"], proof["reports"]["deformed"]
    assert true["all_mutual_pair_medians_px"]["maximum"] < 1e-10
    assert deformed["all_mutual_pair_medians_px"]["median"] > 1
    assert true["measurement_sha256"] == deformed["measurement_sha256"] == bundle.sha256
    assert proof["status"] == "comparison_available" and len(proof["common_pair_indices"]) == 8
    assert not proof["winner_selected"] and proof["admission_effect"] == "none"
    assert not true["candidate_observations_used_for_filter"]
    assert not proof["execution_qualified"] and not proof["navigation_qualified"]


@pytest.mark.parametrize("scale", [7.25, 1e-100])
def test_positive_global_similarity_preserves_the_epipolar_measurement(scale):
    bundle, cameras = projected_fixture(3)
    rotation = cv.Rodrigues(np.array([0.3, -0.25, 0.5]))[0]
    translation = np.array([120.0, -40.0, 17.0]) * scale
    transformed = {}
    for name, cam in cameras.items():
        matrix = np.asarray(cam.camera_to_world)
        pose = np.c_[rotation @ matrix[:, :3], scale * rotation @ matrix[:, 3] + translation]
        transformed[name] = replace(
            cam, camera_to_world=tuple(tuple(map(float, row)) for row in pose)
        )
    a = validation.evaluate_candidate(bundle, cameras, budget=budget())
    b = validation.evaluate_candidate(bundle, transformed, budget=budget())
    assert b["all_mutual_pair_medians_px"]["maximum"] < 1e-9
    np.testing.assert_allclose(
        a["all_mutual_pair_medians_px"]["median"],
        b["all_mutual_pair_medians_px"]["median"],
        atol=1e-9,
    )


@pytest.mark.parametrize(
    "model,distortion", [("OPENCV", ()), ("UNKNOWN", ()), ("PINHOLE", (0.01,))]
)
def test_distorted_or_unknown_calibration_is_inconclusive_without_raw_f(model, distortion):
    bundle, cameras = projected_fixture()
    cameras["1.png"] = replace(cameras["1.png"], model=model, distortion=distortion)
    report = validation.evaluate_candidate(bundle, cameras, budget=budget())
    assert report["camera_failures"] == {"1.png": "unsupported_calibration_model"}
    assert report["pairs"][0]["status"] == "inconclusive_camera"
    assert "all_mutual" not in report["pairs"][0]
    assert report["independent_2d_pair_medians_px"]["count"] == 0


def test_zero_translation_is_not_scored_as_perfect_epipolar_geometry():
    bundle, cameras = projected_fixture()
    cameras["1.png"] = cameras["0.png"]
    report = validation.evaluate_candidate(bundle, cameras, budget=budget())
    assert report["pairs"][0]["status"] == "unobservable_translation"
    assert report["all_mutual_pair_medians_px"]["count"] == 0
    assert report["pairs"][0]["all_mutual"]["rotation_only_transfer_px"]["median"] > 1


def test_planar_warning_does_not_veto_otherwise_observable_motion():
    bundle, cameras = projected_fixture()
    pair = replace(bundle.pairs[0], homography_inliers=(True,) * len(bundle.pairs[0].matches))
    planar = validation._seal(
        bundle.width, bundle.height, (pair,), bundle.gray_sha256, bundle.mask_sha256, bundle.recipe
    )
    report = validation.evaluate_candidate(planar, cameras, budget=budget())
    assert report["pairs"][0]["planar_or_rotation_possible"]
    assert report["pairs"][0]["status"] == "evaluated"
    assert not report["execution_qualified"]


def test_time_sampler_is_deterministic_bounded_and_spans_source_without_candidate_input():
    views = [(f"{i}.png", float(i) * 0.2) for i in range(173)]
    first = validation.sample_pairs(views)
    assert first == validation.sample_pairs(views)
    assert len(first) == 32 and len({n for p in first for n in (p.first, p.second)}) <= 48
    assert first[0].first == "0.png" and first[-1].second == "172.png"
    assert all(1 <= int(p.second[:-4]) - int(p.first[:-4]) <= 2 for p in first)
    with pytest.raises(ValueError, match="source_clock"):
        validation.sample_pairs(views[::-1])
    with pytest.raises(ValueError, match="sampling_quota"):
        validation.sample_pairs(views, max_pairs=33)


def test_real_orb_measurement_is_shared_immutable_and_retains_raw_matches():
    rng = np.random.default_rng(9)
    first = rng.integers(0, 256, (360, 640), np.uint8)
    second = cv.warpAffine(first, np.float32([[1, 0, 14], [0, 1, 0]]), (640, 360))
    mask = np.full_like(first, 255)
    before = (first.tobytes(), second.tobytes(), mask.tobytes())
    plan = validation.sample_pairs([("0.png", 0.0), ("1.png", 0.2)])
    bundle = validation.measure_pairs(
        {"0.png": first, "1.png": second}, plan, mask, budget=budget(), world_features=512
    )
    assert len(bundle.pairs[0].matches) >= 24
    assert type(bundle.pairs[0].matches) is tuple
    assert before == (first.tobytes(), second.tobytes(), mask.tobytes())
    a = validation.evaluate_candidate(
        bundle, {"0.png": camera(), "1.png": camera((-0.3, 0.0, 0.0))}, budget=budget()
    )
    b = validation.evaluate_candidate(
        bundle, {"0.png": camera(), "1.png": camera((0.0, -0.3, 0.0))}, budget=budget()
    )
    assert a["measurement_sha256"] == b["measurement_sha256"] == bundle.sha256
    assert a["all_mutual_pair_medians_px"]["median"] < b["all_mutual_pair_medians_px"]["median"]
    assert a["pairs"][0]["mutual_matches"] == len(bundle.pairs[0].matches)
    assert "independent_2d_inliers" in a["pairs"][0]


def test_duplicate_physical_pixels_do_not_enter_seeded_f_or_h_fitting(monkeypatch):
    points = [
        cv.KeyPoint(float(40 + (i % 5) * 25), float(40 + (i // 5) * 25), 31.0) for i in range(10)
    ]
    points += [points[0], points[1]]
    descriptors = np.zeros((12, 32), np.uint8)
    monkeypatch.setattr(
        cv,
        "ORB_create",
        lambda **kwargs: SimpleNamespace(
            detectAndCompute=lambda gray, mask: (points, descriptors.copy())
        ),
    )

    class Matcher:
        def knnMatch(self, first, second, k):
            return [[cv.DMatch(i, i, 0.0), cv.DMatch(i, (i + 1) % 12, 10.0)] for i in range(12)]

    monkeypatch.setattr(cv, "BFMatcher", lambda *args: Matcher())
    seeds, lengths = [], []
    monkeypatch.setattr(cv, "setRNGSeed", seeds.append)

    def fit(first, second, *args, **kwargs):
        assert seeds[-1] == 17
        lengths.append(len(first))
        return np.eye(3), np.ones((len(first), 1), np.uint8)

    monkeypatch.setattr(cv, "findFundamentalMat", fit)
    monkeypatch.setattr(cv, "findHomography", fit)
    gray = np.zeros((360, 640), np.uint8)
    bundle = validation.measure_pairs(
        {"a": gray, "b": gray},
        (validation.PairSpec("a", "b", 0.0, 0.2),),
        np.full_like(gray, 255),
        budget=budget(),
    )
    assert lengths == [10, 10] and seeds == [17, 17]
    assert len(bundle.pairs[0].matches) == 12  # Raw measurements remain inspectable.
    assert bundle.pairs[0].physical_duplicate_matches == 2
    assert sum(bundle.pairs[0].fundamental_inliers) == 10
    assert dict(bundle.recipe)["ransac_seed"] == 17
    assert "not_verified_here" in dict(bundle.recipe)["mask_support"]


def test_insufficient_or_missing_pair_cannot_create_a_comparison_preference():
    bundle, cameras = projected_fixture(8)
    missing = dict(cameras)
    del missing["4.png"]
    result = validation.compare_candidates(
        bundle, {"complete": cameras, "missing": missing}, budget=budget()
    )
    assert result["status"] == "inconclusive" and not result["winner_selected"]
    assert result["reports"]["missing"]["incomplete"]


def test_changed_measurements_and_invalid_pose_are_refused():
    bundle, cameras = projected_fixture()
    changed = replace(bundle.pairs[0], matches=bundle.pairs[0].matches[:-1])
    with pytest.raises(ValueError, match="measurements"):
        validation.evaluate_candidate(replace(bundle, pairs=(changed,)), cameras, budget=budget())
    with pytest.raises(ValueError, match="bundle_changed"):
        validation.evaluate_candidate(
            replace(bundle, mask_sha256="c" * 64), cameras, budget=budget()
        )
    reflected = np.c_[np.diag([-1.0, 1.0, 1.0]), [0.0, 0.0, 0.0]]
    cameras["1.png"] = replace(cameras["1.png"], camera_to_world=tuple(map(tuple, reflected)))
    report = validation.evaluate_candidate(bundle, cameras, budget=budget())
    assert report["pairs"][0]["status"] == "inconclusive_camera"


def test_shared_budget_checks_resource_errors_and_deadline_after_callback():
    now = [0.0]

    def delayed_checkpoint():
        now[0] = 2.0

    with pytest.raises(RuntimeError, match="time_quota"):
        validation.Budget(delayed_checkpoint, max_seconds=1, clock=lambda: now[0]).check()
    bundle, cameras = projected_fixture()

    def failed_checkpoint():
        raise RuntimeError("resource_probe_unavailable")

    with pytest.raises(RuntimeError, match="resource_probe_unavailable"):
        validation.evaluate_candidate(bundle, cameras, budget=validation.Budget(failed_checkpoint))
    now[0] = 0.0
    clock_budget = validation.Budget(lambda: None, clock=lambda: now[0])
    now[0] = -1.0
    with pytest.raises(RuntimeError, match="clock_regressed"):
        clock_budget.check()
