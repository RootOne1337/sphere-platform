import math

import cv2
import numpy as np

from scripts.pilot.world_map_lab.live_destination_atlas import Locator
from scripts.pilot.world_map_lab.stationary_walk_views import StationaryWalkViews


def test_rotation_recovery_refits_world_points_and_rejects_a_remote_anchor_or_unrelated_image():
    rng = np.random.default_rng(971)
    gray = cv2.GaussianBlur(rng.integers(0, 256, (360, 640), dtype=np.uint8), (3, 3), 0)
    k = np.float64([[290, 0, 319.5], [0, 290, 179.5], [0, 0, 1]])
    uv = cv2.goodFeaturesToTrack(gray, 500, 0.02, 7).reshape(-1, 2)
    rays = np.column_stack((uv, np.ones(len(uv)))) @ np.linalg.inv(k).T
    depth = rng.uniform(7, 40, (len(uv), 1))
    world_to_camera = np.array([[0, -1, 0], [0, 0, -1], [1, 0, 0]])
    bank = Locator.__new__(Locator)
    bank.meta = dict(source="source-map-grid", independentScenery=True)
    bank.k, bank.origin = k, np.array([30.0, -17.5, 5.3])
    bank.views = [gray]
    bank.track_offsets, bank.track_pixels = [0, len(uv)], uv
    bank.track_xyz = (rays * depth @ world_to_camera).astype(np.float32)
    tracker = StationaryWalkViews(bank)
    turn = cv2.Rodrigues(np.float64([0, math.radians(8), 0]))[0]
    test_view = cv2.warpPerspective(gray, k @ turn @ np.linalg.inv(k), (640, 360))
    found = tracker.locate(test_view, bank.origin)
    assert found and math.dist(found["eye"], bank.origin) < 0.1
    assert found["supports"] >= 100
    assert tracker.locate(test_view, bank.origin + [10, 0, 0]) is None
    unrelated = rng.integers(0, 256, gray.shape, dtype=np.uint8)
    assert tracker.locate(unrelated, bank.origin) is None
