import numpy as np
import pytest

from scripts.pilot.world_map_lab.pedestrian_scene import WalkingSceneGuard
from scripts.pilot.world_map_lab.pedestrian_surface import FootSurface
from scripts.pilot.world_map_lab.project_ariane_roads import PEDESTRIAN_MATERIAL


def test_ariane_pedestrian_materials_keep_mixed_and_bike_tiles_out():
    for name in ("lf_arztrot2", "arzpark_tile4", "arzpark_brick5", "srd_bruschatka2"):
        assert PEDESTRIAN_MATERIAL.fullmatch(name)
    for name in ("wolv_trot_grass", "wolv_trot4_srd", "arzpark_bike1", "arzpark_grav1", "lf_arzgrass1"):
        assert not PEDESTRIAN_MATERIAL.fullmatch(name)


def test_exit_existing_overlap_but_never_cross_a_new_obstacle():
    surface = FootSurface.__new__(FootSurface)

    def run(obstacles, start, end):
        def sweep(a, b):
            return sum(left <= b[0] and right >= a[0] for left, right in obstacles), True

        surface.sweep = sweep
        return surface.clear_or_exiting(np.array([start, 0, 0]), np.array([end, 0, 0]))

    assert run([(-1, 0.4)], 0, 2.0)
    assert not run([(0.7, 0.8)], 0, 2.0)
    assert not run([(-1, 0.4), (0.9, 1.0)], 0, 2.0)
    assert not run([(-1, 2.4)], 0, 3.0)


def test_cut_latches_until_fresh_absolute_exterior_pose():
    guard = WalkingSceneGuard()
    outside = np.full((72, 128, 3), [40, 55, 48], np.uint8)
    room = np.full_like(outside, [210, 180, 140])
    assert not guard.observe(outside)
    assert not guard.observe(outside + 5)
    assert guard.observe(room)
    assert guard.observe(room)
    guard.confirm_world_pose()
    assert not guard.observe(room)


@pytest.mark.parametrize(
    ("eye", "floors", "accepted"),
    [(12.6, [11.1], True), (10.9, [11.1], False), (11.1, [], False), (22.5, [10, 21], True)],
)
def test_pose_requires_reachable_floor_height(eye, floors, accepted):
    surface = FootSurface.__new__(FootSurface)

    class Road:
        def levels(self, x, y, mode):
            assert mode == "walk"
            return floors

    surface.road = Road()
    surface._measure = lambda *_: {"profile": [dict(floor=None, water=None)]}
    assert (surface.ground_support([0, 0, eye], 1.55) is not None) == accepted


def test_floor_at_navmesh_gap_keeps_pose_but_not_water_or_unsupported_height():
    surface = FootSurface.__new__(FootSurface)

    class Road:
        def levels(self, x, y, mode):
            return []

    surface.road = Road()
    sample = {"floor": 25.477, "water": None}
    surface._measure = lambda *_: {"profile": [sample]}
    support = surface.ground_support([0, 0, 27.16], 1.55)
    assert support.height == pytest.approx(25.477)
    assert not support.on_mesh
    assert surface.ground_support([1, 1, 24], 1.55) is None
    assert surface.ground_support([1, 1, 28], 1.55) is None
    sample["water"] = 25.46
    assert surface.ground_support([0, 0, 27.16], 1.55) is None


def test_route_entrance_must_be_clear_at_actual_detour_endpoint():
    surface = FootSurface.__new__(FootSurface)

    class Road:
        def levels(self, x, y, mode):
            return [0.0]

        def query(self, name, **params):
            return {"status": "complete", "length": 9.8, "path": [[0.2, 0, 0], [10, 0, 0]]}

    surface.road = Road()
    surface.visibility = None
    surface.clear_or_exiting = lambda a, b: False
    assert surface.connection([0, 0, 1.55], [10, 0, 0], 0) is None
    surface.clear_or_exiting = lambda a, b: True
    assert surface.connection([0, 0, 1.55], [10, 0, 0], 0)[:2] == [[0, 0, 0], [0.2, 0, 0]]
    assert surface.aim([0, 0, 1.55], 1.55, [0.2, 0]) == pytest.approx([0.2, 0])


def test_sidewalk_lookahead_shortens_at_bend_instead_of_leaving_pavement():
    surface = FootSurface.__new__(FootSurface)
    surface.visibility = None
    surface.sweep = lambda start, end: (0, end[0] < 1)
    aim = surface.pavement_aim([0, 0, 1.55], 1.55, [[2, 1, 0], [0.5, 0, 0]])
    assert aim == pytest.approx([0.5, 0])
    assert surface.pavement_aim([0, 0, 1.55], 1.55, [[2, 1, 0]]) is None

    class Foliage:
        def exposure(self, eye, end):
            return 0.7 if end[0] > 1 else 0.0

    surface.visibility = Foliage()
    surface.sweep = lambda start, end: (0, True)
    assert surface.pavement_aim([0, 0, 1.55], 1.55, [[2, 1, 0], [0.5, 0, 0]]) == pytest.approx(
        [0.5, 0]
    )


def test_walk_steps_admit_only_the_verified_strip_on_the_same_level():
    surface = FootSurface.__new__(FootSurface)
    ground = dict(floor=0, referenceZ=0, water=None, road=0, paving=None, footpath=None)
    reading = dict(profile=[ground] * 3, bodyIntersections=0)
    surface._measure = lambda *args, **kwargs: reading
    entry, exit = np.array([0, 0, 0]), np.array([12, 0, 0])
    strips = ((entry, exit),)
    assert surface.sweep_route([0.5, 0.15, 0], [1.5, 0.15, 0], strips, None)
    assert not surface.sweep_route([0.5, 1, 0], [1.5, 1, 0], strips, None)
    assert not surface.sweep_route([0.5, 0, 0], [1.5, 0, 0], (), None)
    bent = np.array([[0, 0, 0], [2, 1, 0], [4, 1, 0], [8, 0, 0]])
    assert surface.sweep_route([2, 1, 0], [3, 1, 0], (bent,), None)
    assert not surface.sweep_route([2, 1, 0], [3, 1, 0], (bent[[0,-1]],), None)
    other_level = ((entry + [0, 0, -2], exit + [0, 0, -2]),)
    assert not surface.sweep_route([0.5, 0, 0], [1.5, 0, 0], other_level, None)
    reading["bodyIntersections"] = 1
    assert not surface.sweep_route([0.5, 0, 0], [1.5, 0, 0], strips, None)
