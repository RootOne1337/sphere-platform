import cv2
import numpy as np
import pytest

from scripts.pilot.world_map_lab.live_destination import Trip
from scripts.pilot.world_map_lab.live_destination_atlas import Locator, distributed_surface_support


class Roads:
    def levels(self, x, y):
        return [0.0] if x < 40 else []

    def route(self, start, goal):
        return {"status": "complete", "path": [start, goal.tolist()]}


def pose(x, y=0, z=1.45, heading=0):
    return {"eye": [x, y, z], "heading": heading, "supports": 40}


def test_follow_loss_reacquire_and_stationary_arrival():
    trip = Trip(Roads(), [18, 0, 0], lambda _: True)
    assert trip.decide(pose(0), 0)["reason"] == "confirming_position"
    assert trip.decide(pose(0.2), 0.2)["pedal"] == "throttle"
    assert trip.decide(None, 0.4)["pedal"] == "coast"
    assert trip.decide(pose(17), 0.6)["reason"] == "confirming_position"
    assert trip.decide(pose(17.1), 0.8)["reason"] == "stopping"
    assert trip.decide(pose(17.1), 1.6)["reason"] == "arrived"


def test_height_teleport_and_path_rejection():
    trip = Trip(Roads(), [18, 0, 0], lambda path: len(path) == 1)
    trip.decide(pose(0), 0)
    assert trip.decide(pose(0), 0.2)["reason"] == "outside_visual_coverage"
    assert trip.decide(pose(16), 0.4)["reason"] == "confirming_position"
    trip.decide(pose(5, 0, 7), 0.6)
    assert trip.decide(pose(5, 0, 7), 0.8)["reason"] == "road_level_unknown"
    with pytest.raises(ValueError, match="unreachable_goal"):
        Trip(Roads(), [99, 0, 0], lambda _: True)


def test_coverage_checks_between_waypoints_and_on_stacked_roads():
    atlas = Locator.__new__(Locator)
    atlas.meta = {"coverageRadius": 8.0}
    atlas.trace = np.array([[0, 0, 1.45], [20, 0, 1.45]])
    assert atlas.covers([[2, 0, 0], [4, 0, 0]])
    assert not atlas.covers([[0, 0, 0], [20, 0, 0]])
    assert not atlas.covers([[0, 0, 8]])


def test_stalled_vehicle_does_not_hold_throttle_indefinitely():
    trip = Trip(Roads(), [18, 0, 0], lambda _: True)
    decisions = [trip.decide(pose(0), t / 5) for t in range(24)]
    assert any(item["pedal"] == "throttle" for item in decisions)
    assert decisions[-1]["reason"] == "no_motion"
    assert decisions[-1]["pedal"] == "coast"


def test_wrong_camera_jump_needs_reconfirmation_before_motion():
    trip = Trip(Roads(), [25, 0, 0], lambda _: True)
    trip.decide(pose(0), 0)
    trip.decide(pose(0.15), 0.2)
    rejected = trip.decide(pose(14), 0.4)
    assert rejected["reason"] == "confirming_position" and rejected["pedal"] == "coast"
    assert trip.decide(pose(0.45), 0.6)["reason"] == "confirming_position"


def test_pose_from_inverted_camera_is_ineligible_for_vehicle_control():
    loc = Locator.__new__(Locator)
    loc.meta = {"source": "source-map-grid"}
    loc.k = np.array([[240.0, 0, 320], [0, 240.0, 180.0], [0, 0, 1.0]])
    loc.origin = np.zeros(3)
    world = np.random.default_rng(42).uniform([-7, 10, -4], [7, 18, 4], (140, 3)).astype(np.float32)
    forward = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
    for inverted in (False, True):
        rotation = np.diag([-1.0, -1.0, 1.0]) @ forward if inverted else forward
        uv = cv2.projectPoints(world, cv2.Rodrigues(rotation)[0], np.zeros(3), loc.k, None)[0][:, 0]
        assert (loc.solve(world, uv) is None) == inverted


def test_grid_pose_requires_support_away_from_the_dominant_plane():
    rng = np.random.default_rng(23)
    world = rng.uniform(-12, 12, (100, 3)).astype(np.float32)
    pixels = rng.uniform((0, 0), (639, 359), (100, 2)).astype(np.float32)
    world[:, 0] = 3
    world[:2, 0] = 9
    assert not distributed_surface_support(world, pixels)
    world[:18, 0] = 9
    assert distributed_surface_support(world, pixels)
    pixels[:18] = [128, 128]
    assert not distributed_surface_support(world, pixels)
