import cv2 as cv
import numpy as np

from scripts.pilot.route_viewpoint_seed import camera_rotation_homography, choose_rotation_seed


def test_rotation_seed_recovers_known_warp_under_exposure_change():
    rng = np.random.default_rng(12)
    image = np.full((540, 960), 45, dtype=np.uint8)
    for x, y in rng.integers([120, 65], [840, 475], size=(75, 2)):
        cv.circle(image, (int(x), int(y)), 8, 230, 2)
    mask = np.full_like(image, 255)
    mask[0:110, 0:135] = 0
    calibration = np.array([[640., 0., 479.5], [0., 640., 269.5], [0., 0., 1.]])
    warp = camera_rotation_homography(calibration, -8, 4)
    query = cv.warpPerspective(image, warp, (960, 540), borderValue=45)
    query = (query * .75 + 20).astype(np.uint8)
    measured, score, yaw, pitch = choose_rotation_seed(image, query, mask, calibration)
    assert (yaw, pitch) == (-8, 4)
    np.testing.assert_allclose(measured, warp)
    assert score > .8


def test_rotation_seed_requires_visible_structure():
    image = np.full((540, 960), 120, dtype=np.uint8)
    calibration = np.array([[640., 0., 479.5], [0., 640., 269.5], [0., 0., 1.]])
    assert choose_rotation_seed(image, image, np.full_like(image, 255), calibration) is None
