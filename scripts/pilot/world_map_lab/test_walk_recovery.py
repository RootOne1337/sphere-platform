from concurrent.futures import Future

import numpy as np

from scripts.pilot.world_map_lab.walk_recovery import WalkingRecovery


def test_scene_change_discards_inflight_map_even_if_old_fix_is_good(tmp_path):
    recovery = WalkingRecovery({}, "unused", tmp_path, tmp_path, "test")
    try:
        recovery.pending = Future()
        recovery.samples.append(("old view", b"jpeg"))
        recovery.invalidate()
        recovery.pending.set_result((tmp_path, {"eye": [10, 20, 3]}))
        assert recovery.observe(np.zeros((36, 64, 3), np.uint8), None, scene_changed=True) is None
        assert recovery.pending is None and not recovery.samples
    finally:
        recovery.close()
