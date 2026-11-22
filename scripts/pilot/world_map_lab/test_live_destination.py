import argparse

import cv2
import numpy as np
import pytest

from scripts.pilot.world_map_lab.destination_itinerary import plan
from scripts.pilot.world_map_lab.live_destination import (
    Trip,
    preview_origin,
    probe_atlases,
    probe_start_levels,
    walk_pose_plausible,
    walking_exposure,
)
from scripts.pilot.world_map_lab.live_destination_atlas import (
    Locator,
    MenuBackdrop,
    distributed_surface_support,
    features,
)


class Roads:
    def levels(self, x, y):
        return [0.0] if x < 40 else []

    def route(self, start, goal):
        return {"status": "complete", "path": [start, goal.tolist()]}


def pose(x, y=0, z=1.45, heading=0):
    return {"eye": [x, y, z], "heading": heading, "supports": 40}


def test_walking_exposure_refuses_flat_frames_and_bounds_amplification():
    assert walking_exposure(np.full((64, 64), 18, np.uint8)) is None
    dark = np.tile(np.arange(14, 46, dtype=np.uint8), (24, 1))
    adjusted = walking_exposure(dark)
    assert adjusted.shape == dark.shape
    assert np.all(np.diff(adjusted.astype(int), axis=1) == 4)


def test_walk_weather_fix_refuses_a_spurious_jump_and_keeps_normal_steps():
    previous = (1.0, [550.607, 768.422, 12.705], 1.24)
    assert not walk_pose_plausible(previous, pose(551.673, 768.459, 12.283), 1.2)
    assert walk_pose_plausible(previous, pose(550.753, 768.920, 12.559), 1.2)
    assert walk_pose_plausible(previous, pose(550.753, 768.920, 12.559), 3.0)


def test_preview_origin_is_an_exact_loopback_origin():
    assert preview_origin("http://127.0.0.1:3016") == "http://127.0.0.1:3016"
    for value in ("http://localhost:3016", "http://127.0.0.1:3016/path", "http://127.0.0.1:3016@other.test", "null"):
        with pytest.raises(argparse.ArgumentTypeError):
            preview_origin(value)


def test_launcher_backdrop_requires_exact_landmarks_across_the_view():
    rng = np.random.default_rng(43)
    source = rng.integers(5, 190, size=(360, 640), dtype=np.uint8)
    source = cv2.GaussianBlur(source, (3, 3), 0.6)
    menu = MenuBackdrop(source)
    detector = cv2.SIFT_create(nfeatures=1600, contrastThreshold=0.018)
    overlay = source + 25
    overlay[115:270, 225:415] = 220
    assert menu.matches(features(overlay, detector))
    assert not menu.matches(features(np.roll(source, 12, axis=1), detector))
    isolated = np.zeros(source.shape, np.uint8)
    isolated[:110, :145] = source[:110, :145]
    assert not menu.matches(features(isolated, detector))


def test_probe_can_show_position_without_a_valid_route_level():
    class StackedRoads:
        def levels(self, x, y, mode, **kwargs):
            assert (x, y) == (12, 14)
            if mode == "walk":
                assert kwargs == {"surface": "pavement"}
                return [4, 8]
            return [8, 9]

    assert probe_start_levels(StackedRoads(), (12, 14, 10)) == {"walk": 8, "drive": None}
    assert probe_start_levels(StackedRoads(), (12, 14, 15)) == {"walk": None, "drive": None}


def test_walk_itinerary_requires_pavement_endpoints_and_keeps_crossing_geometry():
    entry, exit = [2, 0, 0], [9, 0, 0]
    stop_a, stop_b = [0, 0, 0], [12, 0, 0]

    class PedestrianMap:
        def levels(self, x, y, mode, surface):
            assert (mode, surface) == ("walk", "pavement")
            return [0] if x in (0, 12) else []

        def query(self, name, mode, surface, **_):
            assert (name, mode, surface) == ("path", "walk", "crossings")
            return {
                "status": "complete",
                "path": [stop_a, entry, exit, stop_b],
                "crossings": [{"entry": entry, "exit": exit}],
            }

    road = PedestrianMap()
    blocked = plan(road, [[1, 0, 0], stop_b], "walk", None, surface="crossings")
    assert blocked["reason"] == "wrong_surface"
    result = plan(road, [stop_a, stop_b], "walk", None, surface="crossings")
    assert result["legs"][0]["crossings"] == [{"entry": entry, "exit": exit}]
    road.query = lambda *args, **kwargs: {"status": "surface_unconfirmed", "path": []}
    result = plan(road, [stop_a, stop_b], "walk", None, surface="crossings")
    assert result == {"status": "unavailable", "reason": "surface_unconfirmed", "stop": 1, "legs": []}


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
