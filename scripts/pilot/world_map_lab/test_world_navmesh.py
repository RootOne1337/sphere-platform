"""Regression checks for stacked roads, seams and endpoint admission in the native build."""

import json
import os
import shutil
from argparse import Namespace
from collections import Counter

import pytest

from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import (
    COLLISION,
    DRIVE,
    FOOT,
    WATER,
    put,
)
from scripts.pilot.world_map_lab.world_navmesh import Network, build, checksum
from scripts.pilot.world_map_lab.serve_world_navmesh import source_verified_crossing_route


def test_crossing_fallback_requires_source_verification():
    start, goal = [0, 0, 0], [10, 0, 0]
    filtered, alternate = [5, 0, 0], [5, 2, 0]

    class Nav:
        def route(self, a, b, **flags):
            return dict(status="complete", length=11, path=[filtered if flags else alternate])

    class Surface:
        allow_alternate = True

        def crossings_on(self, points, *, on_unclassified):
            return [] if points == [start, alternate, goal] and self.allow_alternate else None

    pavement = Surface()
    route = source_verified_crossing_route(Nav(), pavement, start, goal)
    assert route["path"] == [alternate]
    assert route["crossings"] == []
    pavement.allow_alternate = False
    assert source_verified_crossing_route(Nav(), pavement, start, goal)["status"] == "surface_unconfirmed"


def deck(x0, y0, x1, y1, z):
    a, b, c, d = (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)
    return [(a, b, c), (a, c, d)]


@pytest.fixture(scope="module")
def meshes(tmp_path_factory):
    dll = os.environ.get("ARIANE_RECAST_DLL")
    if not dll:
        pytest.skip("build the Recast adapter and set ARIANE_RECAST_DLL")
    root = tmp_path_factory.mktemp("stacked_world")
    shutil.copyfile(dll, root / "ariane-nav.dll")
    source = root / "world-geometry.bin"
    with source.open("wb") as write:
        write.write(b"BRGEO1\0\0")
        stats = Counter()
        for geom in (deck(5, 38, 245, 54, 0), deck(90, 10, 106, 115, 6)):
            put(write, COLLISION, geom, stats)
            put(write, DRIVE, geom, stats)
        ramp = [[(x, y, (x - 140) * 0.29) for x, y, _ in tri] for tri in deck(140, 70, 190, 82, 0)]
        for geom in (ramp, deck(190, 70, 210, 82, 15.5)):
            put(write, COLLISION, geom, stats)
            put(write, DRIVE, geom, stats)
        # A road-material boundary on flat, wide pavement has no vertical obstacle.
        put(write, COLLISION, deck(8, 12, 75, 30, 0), stats)
        put(
            write,
            DRIVE,
            deck(8, 12, 34, 30, 0) + deck(34, 20, 48, 22, 0) + deck(48, 12, 75, 30, 0),
            stats,
        )
        # Both endpoints lie low, with an intervening hill on the same long corridor.
        profile = [(5, 0), (20, 1), (40, 4), (60, 8), (80, 4), (100, 1), (115, 0)]
        for (left, z0), (right, z1) in zip(profile, profile[1:]):
            strip = [
                [(x, y, z0 + (z1 - z0) * (x - left) / (right - left)) for x, y, _ in tri]
                for tri in deck(left, 116, right, 126, 0)
            ]
            for kind in (COLLISION, DRIVE):
                put(write, kind, strip, stats)
        put(write, COLLISION, deck(7, 53, 22, 69, 0), stats)
        put(write, COLLISION, deck(210, 53, 240, 69, 0), stats)
        put(write, DRIVE, deck(5, 65, 60, 75, 2), stats)
        # Two sidewalk ends with a moderate paved detour across the top of a lawn.
        put(write, COLLISION, deck(125, 86, 204, 124, 0), stats)
        for strip in [
            deck(128, 90, 134, 112, 0),
            deck(128, 106, 200, 112, 0),
            deck(194, 90, 200, 112, 0),
        ]:
            put(write, FOOT, strip, stats)
        # Facing walkways separated by eight metres of lawn with a 50 m detour above.
        put(write, COLLISION, deck(211, 83, 248, 125, 0), stats)
        for strip in (
            deck(213, 86, 219, 121, 0),
            deck(227, 86, 233, 121, 0),
            deck(213, 115, 233, 121, 0),
        ):
            put(write, FOOT, strip, stats)
        put(write, COLLISION, deck(4, 85, 70, 105, 0), stats)
        put(write, WATER, deck(5, 86, 17, 104, 2), stats)
        put(write, WATER, deck(10, 38, 20, 54, 1499), stats)
    (root / "geometry.json").write_text(
        json.dumps({"geometrySha256": checksum(source), "placementRevision": "test"})
    )
    report = root / "road.json"
    report.write_text(
        json.dumps(
            {
                "placementRevision": "test",
                "bounds": {"left": 0, "right": 256, "bottom": 0, "top": 128},
            }
        )
    )
    build(Namespace(folder=root, road_report=report, workers=2, modes=["drive", "walk"]))
    return root


def test_tile_seam_and_two_distinct_elevations(meshes):
    with Network(meshes, "drive") as nav:
        assert len(nav.levels(98, 44)) == 2
        assert nav.route([10, 45, 0], [230, 45, 0])["status"] == "complete"
        assert nav.route([98, 45, 0], [98, 45, 6])["status"] == "disconnected"
        assert not nav.levels(30, 70)
        assert nav.route([30, 70, 2], [40, 70, 2])["status"] == "endpoint_unavailable"


def test_walkable_ground_and_water(meshes):
    with Network(meshes, "walk") as nav:
        assert not nav.levels(12, 95)
        assert nav.route([25, 95, 0], [55, 95, 0])["status"] == "complete"
        assert nav.levels(15, 45)
    with Network(meshes, "drive") as nav:
        assert not nav.levels(40, 95)


def test_continuous_incline_and_abrupt_step(meshes):
    with Network(meshes, "drive") as nav:
        assert nav.route([144, 76, 1.16], [186, 76, 13.34])["status"] == "complete"
        assert nav.route([186, 76, 13.34], [202, 76, 15.5])["status"] == "disconnected"


def test_drive_then_walk_reaches_offroad_target(meshes):
    from scripts.pilot.world_map_lab.world_trip import TripPlanner

    with Network(meshes, "drive") as car, Network(meshes, "walk") as foot:
        goal = [225, 64, 0]
        assert not car.levels(*goal[:2])
        trip = TripPlanner({"drive": car, "walk": foot}, meshes).route([20, 45, 0], goal)
        assert [leg["mode"] for leg in trip["legs"]] == ["drive", "walk"]
        assert trip["legs"][0]["path"][-1] == pytest.approx(trip["legs"][1]["path"][0], abs=0.375)


def test_height_profile_follows_the_hill(meshes):
    import numpy as np

    with Network(meshes, "walk") as nav:
        route = nav.route([7, 120, 0.2], [113, 120, 0.2])
        assert route["status"] == "complete"
        path = np.array(route["path"])
        assert float(np.interp(60, path[:, 0], path[:, 2])) == pytest.approx(8, abs=0.45)


def test_explicit_vehicle_pickup_and_dropoff(meshes):
    from scripts.pilot.world_map_lab.world_trip import TripPlanner

    with Network(meshes, "drive") as car, Network(meshes, "walk") as foot:
        trip = TripPlanner({"drive": car, "walk": foot}, meshes)
        route = trip.route([225, 64, 0], [229, 64, 0], [20, 45, 0])
        assert [leg["mode"] for leg in route["legs"]] == ["walk", "drive", "walk"]
        for a, b in zip(route["legs"], route["legs"][1:]):
            assert a["path"][-1] == pytest.approx(b["path"][0], abs=0.375)
        assert not trip.route([225, 64, 0], [229, 64, 0], [20, 45, 100])["legs"]


def test_material_boundary_does_not_remove_physical_clearance(meshes):
    with Network(meshes, "drive") as nav:
        assert nav.route([17, 21, 0], [67, 21, 0])["status"] == "complete"
        assert not nav.levels(40, 16)


def test_local_body_motion_respects_deck_and_requested_distance(meshes):
    from scripts.pilot.world_map_lab.serve_world_navmesh import movement_step

    with Network(meshes, "drive") as nav:
        if not hasattr(nav.dll, "move_body"):
            pytest.skip("adapter predates local surface motion")
        z = nav.levels(98, 44)[-1]
        upper = movement_step(nav, [98, 44, z], [99, 44], "drive")
        assert upper["moved"]
        assert upper["position"][2] == pytest.approx(z, abs=0.15)
        assert upper["position"][:2] == pytest.approx([99, 44], abs=0.1)
        pos = upper["position"]
        for _ in range(20):
            step = movement_step(nav, pos, [pos[0], pos[1] + 1], "drive")
            assert abs(step["position"][1] - pos[1]) <= 1.02
            assert abs(step["position"][2] - z) < 0.25
            pos = step["position"]
        with pytest.raises(ValueError):
            movement_step(nav, pos, [pos[0] + 20, pos[1]], "drive")


def test_taxi_picks_up_between_two_pedestrian_endpoints(meshes):
    from scripts.pilot.world_map_lab.world_trip import TripPlanner

    with Network(meshes, "drive") as drive, Network(meshes, "walk") as walk:
        planner = TripPlanner({"drive": drive, "walk": walk}, meshes)
        a, b = [15, 63, 0], [225, 64, 0]
        assert not drive.levels(*a[:2]) and not drive.levels(*b[:2])
        route = planner.taxi(a, b)
        assert [leg["mode"] for leg in route["legs"]] == ["walk", "drive", "walk"]
        for first, second in zip(route["legs"], route["legs"][1:]):
            assert first["path"][-1] == pytest.approx(second["path"][0], abs=0.375)
        route["legs"].clear()
        assert len(planner.taxi(a, b)["legs"]) == 3
        assert planner.taxi(b, b)["status"] == "already_there"
        assert planner.taxi([15, 63, 100], b)["status"] == "endpoint_unavailable"
        assert planner.taxi([25, 95, 0], b)["reason"] == "no_walk_to_road"
        assert planner.taxi(b, [25, 95, 0])["reason"] == "no_road_to_goal"


def test_reachable_map_does_not_include_an_isolated_pavement(meshes):
    from io import BytesIO

    from PIL import Image

    from scripts.pilot.world_map_lab.taxi_surface import TaxiSurface
    from scripts.pilot.world_map_lab.world_trip import TripPlanner

    with Network(meshes, "drive") as drive, Network(meshes, "walk") as walk:
        surface = TaxiSurface(TripPlanner({"drive": drive, "walk": walk}, meshes), size=511)
        with Image.open(BytesIO(surface.png([25, 95, 0]))) as image:

            def index(x, y):
                return image.getpixel((round(x / 256 * 510), round((128 - y) / 128 * 510)))

            assert index(25, 95) == 1
            assert index(225, 64) == 0
        with pytest.raises(ValueError):
            surface.png([25, 95, 100])


def test_walk_accepts_worthwhile_lawn_shortcuts_and_prefers_a_nearby_sidewalk(meshes):
    with Network(meshes, "walk") as foot:
        mild = foot.route([131, 102, 0], [197, 102, 0])
        assert mild["status"] == "complete"
        assert any(y >= 105 for _, y, _ in mild["path"])
        # On the same unmarked floor a short cross-lawn link is still navigable.
        across = foot.route([155, 92, 0], [160, 92, 0])
        assert across["status"] == "complete"
        assert across["length"] < 6
        saving = foot.route([216, 90, 0], [230, 90, 0])
        assert saving["status"] == "complete"
        assert saving["length"] < 20


def test_pedestrian_release_must_be_local_and_transfers_bound_to_it(tmp_path, meshes):
    from scripts.pilot.world_map_lab.serve_world_navmesh import pedestrian_release
    from scripts.pilot.world_map_lab.world_trip import TripPlanner

    assert pedestrian_release(tmp_path) == tmp_path
    marker = tmp_path / "pedestrian-release.json"
    marker.write_text('{"release":"walk-v1"}')
    assert pedestrian_release(tmp_path) == tmp_path / "pedestrian-releases" / "walk-v1"
    marker.write_text('{"release":"../wrong"}')
    with pytest.raises(ValueError, match="release"):
        pedestrian_release(tmp_path)
    with Network(meshes, "drive") as drive, Network(meshes, "walk") as walk:
        with pytest.raises(ValueError, match="transfer index"):
            TripPlanner({"drive": drive, "walk": walk}, meshes, walk_folder=tmp_path)


def test_pavement_only_uses_painted_walkways_and_refuses_unmarked_floor(meshes):
    with Network(meshes, "walk") as foot:
        if not hasattr(foot.dll, "query_pavement_path"):
            pytest.skip("adapter predates pavement-only paths")
        direct = foot.route([216, 90, 0], [230, 90, 0])
        paved = foot.route([216, 90, 0], [230, 90, 0], pavement=True)
        assert direct["status"] == paved["status"] == "complete"
        assert direct["length"] < 20 and paved["length"] > 50
        assert max(q[1] for q in paved["path"]) >= 115
        rejected = foot.route([223, 90, 0], [230, 90, 0], pavement=True)
        assert rejected["status"] == "endpoint_unavailable"
        assert not rejected["path"]
