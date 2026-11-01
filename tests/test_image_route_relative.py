import math

import cv2
import numpy as np
import pytest

from motor_worker.image_route_relative import estimate_relative_goal

K = np.array([[650.0, 0, 480.0], [0, 650.0, 270.0], [0, 0, 1.0]])


def scene(*, translation=(0.6, 0.1, 0.3), yaw=0.08, depth=1.0, count=150):
    rng = np.random.default_rng(741)
    z = rng.uniform(3, 12, count) * depth
    xyz = np.column_stack(
        (rng.uniform(-0.55, 0.55, count) * z, rng.uniform(-0.3, 0.3, count) * z, z)
    )
    R = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    target = xyz @ R.T + np.asarray(translation)

    def project(x):
        p = x @ K.T
        return p[:, :2] / p[:, 2, None]

    a, b = project(xyz), project(target)
    keep = (
        (target[:, 2] > 0)
        & (a[:, 0] >= 0)
        & (a[:, 0] < 960)
        & (a[:, 1] >= 0)
        & (a[:, 1] < 540)
        & (b[:, 0] >= 0)
        & (b[:, 0] < 960)
        & (b[:, 1] >= 0)
        & (b[:, 1] < 540)
    )
    return a[keep], b[keep], R


def run(a, b, K0=K):
    return estimate_relative_goal(a, b, K0, width=960, height=540)


def test_translation_sign_rotation_and_unit_no_authority():
    t = np.array([0.6, 0.1, 0.3])
    a, b, R = scene(translation=t)
    got = run(a, b)
    assert got["status"] == "goal_direction", got
    assert np.allclose(got["Rtarget_from_query"], R, atol=0.015)
    direction = -R.T @ t
    direction /= np.linalg.norm(direction)
    assert np.dot(got["goal_direction_query_camera"], direction) > 0.995
    assert np.linalg.norm(got["goal_direction_query_camera"]) == pytest.approx(1.0)
    assert got["support"]["pose_inliers"] >= 20 and got["support"]["median_parallax_deg"] >= 0.3
    for key in (
        "position_known",
        "arrival_confirmed",
        "execution_qualified",
        "metric_scale_known",
        "camera_vehicle_alignment_known",
    ):
        assert got[key] is False


def test_pure_rotation_never_invents_translation():
    a, b, R = scene(translation=(0, 0, 0), yaw=0.08)
    got = run(a, b)
    assert got["status"] in ("orientation_only", "unknown"), got
    assert got["goal_direction_query_camera"] is None
    if got["status"] == "orientation_only":
        assert np.allclose(got["Rtarget_from_query"], R, atol=0.01)


def test_near_zero_parallax_never_invents_translation():
    a, b, _ = scene(translation=(0.001, 0, 0), depth=4.0)
    got = run(a, b)
    assert got["status"] in ("orientation_only", "unknown"), got
    assert got["goal_direction_query_camera"] is None


def test_outliers_with_majority_consensus():
    a, b, R = scene()
    rng = np.random.default_rng(8)
    b = b.copy()
    b[:25] = rng.uniform([0, 0], [959, 539], (25, 2))
    got = run(a, b)
    assert got["status"] == "goal_direction", got
    assert np.allclose(got["Rtarget_from_query"], R, atol=0.04)
    assert got["support"]["pose_inliers"] < len(a)


def test_multiple_essential_matrices_choose_supported_hypothesis(monkeypatch):
    a, b, R = scene()
    original = cv2.findEssentialMat
    E, mask = original(a, b, K, method=cv2.RANSAC, prob=0.999, threshold=1.5)
    wrong = np.diag([1.0, 1.0, 0.0])
    monkeypatch.setattr(
        cv2, "findEssentialMat", lambda *args, **kw: (np.vstack((wrong, E[:3])), mask)
    )
    real_recover = cv2.recoverPose

    def recover(matrix, *args, **kwargs):
        if np.array_equal(matrix, wrong):
            raise cv2.error("invalid candidate")
        return real_recover(matrix, *args, **kwargs)

    monkeypatch.setattr(cv2, "recoverPose", recover)
    got = run(a, b)
    assert got["status"] == "goal_direction", got
    assert np.allclose(got["Rtarget_from_query"], R, atol=0.03)


def test_no_spatial_support_never_estimates_a_goal():
    a = np.random.default_rng(2).uniform([480, 270], [510, 300], (50, 2))
    b = a + [2, 1]
    assert run(a, b)["status"] == "unknown"


@pytest.mark.parametrize(
    "kind", ["empty", "nan", "bad_k", "out_of_bounds", "duplicate", "too_many"]
)
def test_invalid_data_returns_unknown(kind):
    a, b, _ = scene()
    intrinsics = K.copy()
    if kind == "empty":
        a = b = np.empty((0, 2))
    if kind == "nan":
        a[0, 0] = np.nan
    if kind == "bad_k":
        intrinsics[0, 0] = 0
    if kind == "out_of_bounds":
        a[0, 0] = 960
    if kind == "duplicate":
        a[1] = a[0]
    if kind == "too_many":
        a = b = np.zeros((4097, 2))
    got = run(a, b, intrinsics)
    assert got["status"] == "unknown" and got["execution_qualified"] is False
