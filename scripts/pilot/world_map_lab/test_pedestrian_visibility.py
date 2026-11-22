import numpy as np
import pytest

from scripts.pilot.world_map_lab.pedestrian_visibility import foliage_exposure, slice_segments


def test_eye_level_leaves_affect_approach_but_canopy_and_narrow_posts_have_free_sides():
    upright = np.array(
        [[[1, -0.3, 0], [1, 0.3, 0], [1, 0.3, 3]], [[1, -0.3, 0], [1, 0.3, 3], [1, -0.3, 3]]]
    )
    lines = slice_segments(upright, 1.5)
    assert len(lines) == 2
    assert foliage_exposure(lines, [0, 0], [2, 0]) > 0.25
    assert foliage_exposure(lines, [0, 1.5], [2, 1.5]) == 0
    assert foliage_exposure(lines, [1, 0], [3, 0]) < foliage_exposure(lines, [3, 0], [1, 0])
    assert not len(slice_segments(upright + [0, 0, 4], 1.5))
    assert foliage_exposure(slice_segments(upright, -1), [0, 0], [2, 0]) == pytest.approx(0)
