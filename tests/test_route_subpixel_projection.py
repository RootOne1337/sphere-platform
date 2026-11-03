"""Current-inlier projection checks; no query, pose fitting or dataset replay."""

import math

import numpy as np
import pytest

from motor_worker.route_confirmation import subpixel_projection_consistency
from motor_worker.route_localization import inlier_spatial_support


def project(world, center, rotation, calibration):
    camera = (world - center) @ rotation.T
    image = camera @ calibration.T
    return image[:, :2] / image[:, 2:]


def scene():
    rng = np.random.default_rng(530)
    world = rng.uniform([-2., -1.2, 3.], [2., 1.2, 7.], (160, 3))
    center = np.array([.0004, .0001, 0.])
    old_center, rotation = np.zeros(3), np.eye(3)
    calibration = np.array([[300., 0., 480.], [0., 302., 270.], [0., 0., 1.]])
    image = project(world, center, rotation, calibration)
    assert inlier_spatial_support(image)
    return world, image, center, rotation, old_center, rotation.copy(), calibration


def test_tiny_translation_requires_both_actual_reprojections():
    args = scene()
    accepted, maximum = subpixel_projection_consistency(*args)
    current = project(args[0], args[2], args[3], args[6])
    previous = project(args[0], args[4], args[5], args[6])
    assert accepted and 0 < maximum < .5
    assert maximum == pytest.approx(np.abs(current - previous).max())
    np.testing.assert_allclose(current, args[1], atol=1e-12)
    assert np.linalg.norm(previous - args[1], axis=1).max() < 3


def test_identical_pose_returns_zero_without_inventing_motion():
    world, image, center, rotation, _, _, calibration = scene()
    accepted, maximum = subpixel_projection_consistency(
        world, image, center, rotation, center.copy(), rotation.copy(), calibration)
    assert accepted and maximum == 0.


def test_one_large_delta_fails_even_with_all_other_points_indistinguishable():
    world, _, _, rotation, old_center, old_rotation, calibration = scene()
    world = np.concatenate((world, [[0., 0., .05]]))
    center = np.array([.0001, 0., 0.])
    image = project(world, center, rotation, calibration)
    # Both poses pass the normal <=3px reprojection test for every point.
    errors = np.linalg.norm(project(world, old_center, old_rotation, calibration) - image, axis=1)
    assert (errors <= 3).all() and (errors[:-1] < .02).all()
    accepted, maximum = subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration)
    assert not accepted and maximum == pytest.approx(.6)


@pytest.mark.parametrize("pixel_delta,accepted", [(.499, True), (.5, True), (.501, False)])
def test_all_point_coordinate_bound_is_inclusive_and_not_rounded(pixel_delta, accepted):
    world, _, _, rotation, old_center, old_rotation, calibration = scene()
    world = np.concatenate((world, [[0., 0., .125]]))
    center = np.array([pixel_delta * .125 / calibration[0, 0], 0., 0.])
    image = project(world, center, rotation, calibration)
    result, maximum = subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration)
    assert result == accepted
    assert maximum == pytest.approx(pixel_delta, abs=1e-12)


@pytest.mark.parametrize("which", ["current", "old"])
def test_bad_reprojection_of_either_pose_cannot_be_hidden_by_small_other_pose(which):
    world, image, center, rotation, old_center, old_rotation, calibration = scene()
    if which == "current":
        center = np.array([1., 0., 0.])
    else:
        old_center = np.array([1., 0., 0.])
    assert subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration) == (False, None)


@pytest.mark.parametrize("which", ["world", "image", "center", "rotation", "old_center",
                                   "old_rotation", "calibration"])
def test_nonfinite_inputs_refuse(which):
    args = list(scene())
    at = ["world", "image", "center", "rotation", "old_center", "old_rotation",
          "calibration"].index(which)
    args[at] = args[at].copy()
    args[at].flat[0] = np.nan
    assert subpixel_projection_consistency(*args) == (False, None)


@pytest.mark.parametrize("depth", [0., -1.])
def test_one_nonpositive_depth_refuses_the_whole_set(depth):
    world, image, center, rotation, old_center, old_rotation, calibration = scene()
    world[0, 2] = depth
    assert subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration) == (False, None)


def test_old_pose_behind_camera_is_rejected_even_when_current_pose_is_valid():
    world, image, center, rotation, old_center, _, calibration = scene()
    old_rotation = np.diag([1., -1., -1.])
    assert subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration) == (False, None)


def test_planar_world_is_rejected_despite_good_image_spread_and_exact_projection():
    world, _, center, rotation, old_center, old_rotation, calibration = scene()
    world[:, 2] = 4.
    image = project(world, center, rotation, calibration)
    assert inlier_spatial_support(image)
    assert subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration) == (False, None)


def test_collinear_world_is_not_valid_geometric_evidence():
    world, _, center, rotation, old_center, old_rotation, calibration = scene()
    t = np.linspace(-2., 2., len(world))
    world = np.column_stack((t, t * .5, t * .2 + 5.))
    image = project(world, center, rotation, calibration)
    assert subpixel_projection_consistency(
        world, image, center, rotation, old_center, old_rotation, calibration) == (False, None)


@pytest.mark.parametrize("scale", [.1, 3.7, 100.])
def test_positive_sim3_including_rotated_world_axes_and_translation(scale):
    args = scene()
    expected = subpixel_projection_consistency(*args)
    world, image, center, rotation, old_center, old_rotation, calibration = args
    q = np.array([[0., -1., 0.], [.6, 0., -.8], [.8, 0., .6]])
    shift = np.array([11., -6., 3.])
    transformed = subpixel_projection_consistency(
        scale * world @ q.T + shift, image,
        scale * q @ center + shift, rotation @ q.T,
        scale * q @ old_center + shift, old_rotation @ q.T, calibration)
    assert transformed[0] == expected[0]
    assert transformed[1] == pytest.approx(expected[1], abs=2e-11)


def test_inputs_are_not_mutated():
    args = scene()
    before = [value.copy() for value in args]
    subpixel_projection_consistency(*args)
    for value, original in zip(args, before, strict=True):
        np.testing.assert_array_equal(value, original)


def yaw(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, 0., s], [0., 1., 0.], [-s, 0., c]])


@pytest.mark.parametrize("angle", [.1, .3, .5])
def test_genuine_in_place_yaw_compensates_rotation_in_center_check(angle):
    world, _, _, _, _, _, calibration = scene()
    center, current, previous = np.zeros(3), yaw(angle), np.eye(3)
    image = project(world, center, current, calibration)
    assert inlier_spatial_support(image)
    # Actual old/current views differ visibly; both centre hypotheses are
    # compared using the measured CURRENT rotation, not the old view direction.
    assert np.abs(project(world, center, previous, calibration) - image).max() > 10
    accepted, maximum = subpixel_projection_consistency(
        world, image, center, current, center.copy(), previous, calibration)
    assert accepted and maximum == 0.


@pytest.mark.parametrize("angle", [1.0501, 1.2])
def test_rotation_compensation_cannot_waive_original_turn_limit(angle):
    camera_points, _, _, _, _, _, calibration = scene()
    current, previous, center = yaw(angle), np.eye(3), np.zeros(3)
    world = camera_points @ current
    image = project(world, center, current, calibration)
    assert inlier_spatial_support(image)
    assert ((world - center) @ current.T)[:, 2].min() > 0
    assert subpixel_projection_consistency(
        world, image, center, current, center.copy(), previous, calibration) == (False, None)


def test_yaw_compensation_does_not_hide_bad_previous_center_reprojection():
    world, _, _, _, _, _, calibration = scene()
    center, current, previous = np.zeros(3), yaw(.3), np.eye(3)
    image = project(world, center, current, calibration)
    assert inlier_spatial_support(image)
    assert subpixel_projection_consistency(
        world, image, center, current, np.array([1., 0., 0.]), previous,
        calibration) == (False, None)
