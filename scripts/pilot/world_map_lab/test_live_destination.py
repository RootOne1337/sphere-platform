import cv2
import numpy as np
import pytest

from scripts.pilot.world_map_lab.live_destination import Trip, probe_atlases
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


def test_vehicle_stops_at_each_waypoint_and_reacquires_for_next_leg():
    trip = Trip(Roads(), [5, 0, 0], lambda _: True)
    trip.next_stops = [[15, 0, 0]]
    assert trip.decide(pose(5), 0)["reason"] == "confirming_position"
    assert trip.decide(pose(5), 0.2)["reason"] == "stopping"
    assert trip.decide(pose(5), 1.0)["reason"] == "waypoint_reached"
    assert trip.decide(pose(5), 1.2)["reason"] == "confirming_position"
    assert trip.stop_index == 1
    assert trip.decide(None, 1.4)["pedal"] == "coast"
    assert trip.decide(pose(15), 1.6)["reason"] == "confirming_position"
    assert trip.decide(pose(15), 1.8)["reason"] == "stopping"
    assert trip.decide(pose(15), 2.6)["reason"] == "arrived"


def test_different_lenses_must_agree_before_reporting_a_search_pose():
    loc = Locator.__new__(Locator)
    loc.k = np.array([[300, 0, 319.5], [0, 300, 179.5], [0, 0, 1.0]])
    stream = loc.k.copy()
    stream[0, 0] = stream[1, 1] = 202
    loc.configure_search_lenses(stream, [70, 70])
    assert len(loc.search_lenses) == 3
    with pytest.raises(ValueError):
        loc.configure_search_lenses(stream, [float("nan")])
    loc.configure_search_lenses(stream, [70])
    loc.solve_with_camera = lambda camera, *_: pose(6 if camera[0, 0] > 400 else 0)
    assert loc.solve(None, None) is None
    loc.solve_with_camera = lambda camera, *_: pose(0.1) if camera[0, 0] > 400 else None
    assert loc.solve(None, None)["eye"] == [0.1, 0, 1.45]


def test_overlapping_search_atlases_reuse_features_and_reject_conflicting_locations():
    class Index:
        def __init__(self, x, strength):
            self.x, self.strength, self.descriptions = x, strength, 0

        def describe(self, gray):
            self.descriptions += 1
            return "pixels", "descriptors"

        def locate_features(self, gray, pixels, descriptors):
            assert (pixels, descriptors) == ("pixels", "descriptors")
            return dict(eye=[self.x, 0, 2], heading=0, supports=self.strength)

        def covers(self, path):
            return True

    first, overlap = Index(10, 32), Index(10.1, 60)
    result = probe_atlases(None, first, {"overlap": overlap})
    assert not result["ambiguous"] and result["district"] == "overlap"
    assert (first.descriptions, overlap.descriptions) == (1, 0)
    conflict = probe_atlases(None, first, {"overlap": overlap, "similar": Index(45, 80)})
    assert conflict == dict(pose=None, district=None, ambiguous=True)


def test_nearby_repeated_object_needs_distant_street_support():
    loc = Locator.__new__(Locator)
    loc.origin = np.zeros(3)
    loc.meta = {"source": "source-map-grid", "independentScenery": True}
    loc.k = np.array([[340.0, 0.0, 320.0], [0.0, 340.0, 180.0], [0.0, 0.0, 1.0]])
    rng = np.random.default_rng(101)
    world = rng.uniform([-3, 5, -2], [3, 8, 2], (150, 3)).astype(np.float32)
    rotation = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])

    def project():
        return cv2.projectPoints(world, cv2.Rodrigues(rotation)[0], np.zeros(3), loc.k, None)[0][
            :, 0
        ]

    assert loc.solve(world, project()) is None
    world[::3] *= 3
    assert loc.solve(world, project()) is not None


def test_lane_reference_samples_follow_bends_and_include_last_surface():
    from scripts.pilot.world_map_lab.capture_district_references import road_sites

    class Map:
        def route(self, start, end):
            return dict(status="complete", path=[start, [0, 0, 0], [3, 0, 0], end])

    sites = list(road_sites(Map(), [0, 0, 0, 3, 5, 0], 2))
    assert [s[:3] for s in sites] == [
        (0, 0, 1.45),
        (2, 0, 1.45),
        (3, 1, 1.45),
        (3, 3, 1.45),
        (3, 5, 1.45),
    ]
    assert sites[0][3] == 0 and sites[-1][3] == pytest.approx(np.pi / 2)


def test_search_only_fallback_uses_existing_features_without_rechecking_main():
    class Passive:
        def locate_features(self, gray, *features):
            assert features == ("uv", "desc")
            return dict(eye=[8, 1, 2], heading=0, supports=48)

        def covers(self, path):
            return True

    result = probe_atlases(
        None, None, {"district": Passive()}, observed=("uv", "desc"), include_main=False
    )
    assert result["district"] == "district" and result["pose"]["eye"] == [8, 1, 2]


def test_progressive_drive_requires_a_covered_stopping_horizon():
    def seen(points):
        return all(p[0] <= 9 for p in points)

    trip = Trip(Roads(), [18, 0, 0], lambda p: len(p) == 1, local_covers=seen)
    assert trip.decide(pose(0), 0)["pedal"] == "coast"
    assert trip.decide(pose(0.1), 0.2)["reason"] == "following"
    assert trip.extend_visual
    result = trip.decide(pose(4.5), 0.65)
    assert result["pedal"] == "brake" and result["reason"] == "stopping"
    result = trip.decide(pose(4.5), 1)
    assert result["pedal"] == "coast" and result["reason"] == "outside_visual_coverage"
    assert trip.decide(None, 1.3)["pedal"] == "coast"
