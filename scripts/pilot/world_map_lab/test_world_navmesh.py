"""Regression checks for stacked roads, seams and endpoint admission in the native build."""

import json
import os
import shutil
from argparse import Namespace
from collections import Counter

import pytest

from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import COLLISION, DRIVE, WATER, put
from scripts.pilot.world_map_lab.world_navmesh import Network, build, checksum


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
        put(write, COLLISION, deck(210, 53, 240, 69, 0), stats)
        put(write, DRIVE, deck(5, 65, 60, 75, 2), stats)
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
