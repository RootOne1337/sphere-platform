import math
from types import SimpleNamespace

import cv2 as cv
import numpy as np
import pytest

from motor_worker.route_localization import RouteLocalizer
from scripts.pilot.route_guided_descriptor_probe import refine_descriptor_pose


def fixture():
    indices = np.arange(30)
    pixels = np.column_stack((120 + 130 * (indices % 6), 90 + 80 * (indices // 6)))
    pixels = pixels.astype(float)
    camera = np.array([[600., 0., 479.5], [0., 600., 269.5], [0., 0., 1.]])
    depth = (4 + (indices % 4) / 2)[:, None]
    world = (np.column_stack((pixels, np.ones(len(pixels)))) @ np.linalg.inv(camera).T) * depth
    descriptors = np.eye(len(indices), 128, dtype=np.float32)
    localizer = SimpleNamespace(cv=cv, np=np, xyz=world, K=camera, descriptors=descriptors,
                               visibility=np.ones((4, len(indices))), lengths=np.array([.4, .4, .4]))
    localizer._nearest = lambda center: (0, 0., 0.)
    localizer._verify_correspondences = lambda xyz, xy: RouteLocalizer._verify_correspondences(localizer, xyz, xy)
    seed = (np.zeros(3), np.eye(3), 24, 0., indices[:24], pixels[:24])
    return localizer, seed, pixels, descriptors


def test_guidance_adds_only_unique_measured_current_matches():
    localizer, seed, pixels, descriptors = fixture()
    # Add a repeated orientation at a seed pixel and a repeated added pixel.
    duplicate_indices = [0, 25]
    query = np.concatenate((pixels, pixels[duplicate_indices]))
    query_descriptors = np.concatenate((descriptors, descriptors[duplicate_indices]))
    refined = refine_descriptor_pose(localizer, seed, query, query_descriptors)
    assert refined[2] == 30
    assert np.unique(refined[4]).size == 30
    assert len(np.unique(refined[5], axis=0)) == 30
    np.testing.assert_array_equal(refined[4][:24], seed[4])
    np.testing.assert_allclose(refined[0], seed[0], atol=1e-6)


@pytest.mark.parametrize("failure", ["seed_support", "center", "angle", "expired"])
def test_guidance_preserves_stock_seed_if_refinement_changes_support_or_expires(failure):
    localizer, seed, pixels, descriptors = fixture()
    calls = []

    def verifier(xyz, xy):
        calls.append(True)
        mask = np.ones(len(xy), bool)
        center, rotation = np.zeros(3), np.eye(3)
        if failure == "seed_support":
            mask[0] = False
        elif failure == "center":
            center[0] = .1
        elif failure == "angle":
            rotation = cv.Rodrigues(np.array([math.radians(3.), 0., 0.]))[0]
        return center, rotation, int(mask.sum()), .1, mask

    localizer._verify_correspondences = verifier
    result = refine_descriptor_pose(localizer, seed, pixels, descriptors,
                                    still_current=lambda: failure != "expired" or not calls)
    assert result is seed
    assert calls == [True]
