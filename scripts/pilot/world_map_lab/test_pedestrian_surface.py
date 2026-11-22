import numpy as np
import pytest

from scripts.pilot.world_map_lab.pedestrian_scene import WalkingSceneGuard, plausible_walk_height
from scripts.pilot.world_map_lab.pedestrian_surface import FootSurface


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
    assert plausible_walk_height(eye, floors) == accepted
