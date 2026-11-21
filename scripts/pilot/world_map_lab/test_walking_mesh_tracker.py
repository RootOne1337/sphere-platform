import math
import threading
import time

import numpy as np

from scripts.pilot.world_map_lab.walking_mesh_tracker import WalkingMeshTracker


def test_mesh_pose_keeps_absolute_world_coordinates_and_rejects_one_facade():
    tracker = WalkingMeshTracker.__new__(WalkingMeshTracker)
    tracker.camera = np.array([[290, 0, 319.5], [0, 290, 179.5], [0, 0, 1.0]])
    rng = np.random.default_rng(138)
    eye = np.array([551.3, -172.4, 11.7])
    rotation = np.float64([[0, -1, 0], [0, 0, -1], [1, 0, 0]])
    pixel = rng.uniform([30, 25], [610, 320], (240, 2))
    ray = np.column_stack((pixel, np.ones(len(pixel)))) @ np.linalg.inv(tracker.camera).T
    for depth, expect_fix in [
        (rng.uniform(6, 44, len(pixel)), True),
        (np.full(len(pixel), 18.0), False),
    ]:
        world = eye + (ray * depth[:, None]) @ rotation
        answer = tracker._solve(world, pixel, eye + [2.0, -1.0, 0.0])
        if expect_fix:
            pose, points, observations = answer
            assert math.dist(pose["eye"], eye) < 0.01
            assert abs(pose["heading"]) < 0.001
            assert len(points) == len(observations) and len(points) >= 200
        else:
            assert answer is None


def test_old_mesh_anchor_cannot_be_renewed_by_stationary_optical_flow():
    tracker = WalkingMeshTracker.__new__(WalkingMeshTracker)
    tracker.lock = threading.Condition()
    tracker.refresh = None
    now = time.monotonic()
    tracker.track = (None, None, None, None, now, now - 6)
    assert tracker.locate(np.zeros((360, 640, 3), np.uint8)) is None
