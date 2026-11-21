import numpy as np

from scripts.pilot.world_map_lab.bake_game_reference_views import plan_views, reproject_depth


def test_keep_headings_and_restart_spacing_on_pedestrian_finish():
    def view(phase, station, yaw):
        return {"phase": phase, "s": station, "pose": [station, 1, 2, yaw, 0]}

    views = [
        view(0, 0, 0),
        view(0, 0, 1),
        view(0, 2, 0),
        view(0, 4, 0),
        view(1, 0, 0),
        view(1, 6, 0),
        view(1, 12, 0),
        view(2, 0, 0),
    ]
    sites = plan_views(views, 4, 6, 8)
    assert [site["referenceIndex"] for site in sites] == [0, 1, 3, 4, 5, 7]
    assert sites[0]["eye"] == sites[1]["eye"] and sites[0]["target"] != sites[1]["target"]


def test_reproject_depth_reuses_intrinsics_for_previously_native_references():
    depth = np.arange(81, dtype=np.uint16).reshape(9, 9) + 1
    np.testing.assert_array_equal(reproject_depth(depth, 40, 40), depth)
    wide = reproject_depth(depth, 40, 20)
    assert wide[4, 4] == depth[4, 4]
    assert wide[4, 5] == depth[4, 6]
    assert wide[0, 0] == 0
