import json
import time
from concurrent.futures import Future

import numpy as np

from scripts.pilot.world_map_lab.walk_recovery import WalkingRecovery
from scripts.pilot.world_map_lab.world_scene_acquisition import RecentWalkProbe


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


def test_recent_walk_hint_requires_matching_revision_and_fresh_timestamp(tmp_path):
    p = tmp_path / "recent-walk-fix.json"
    row = dict(revision="test", capturedUnix=time.time(), pose=dict(eye=[4, 2, 8], heading=0.3))
    p.write_text(json.dumps(row))
    assert RecentWalkProbe(tmp_path, "test").seed == row["pose"]
    assert RecentWalkProbe(tmp_path, "other").seed is None
    row["capturedUnix"] -= 1400
    p.write_text(json.dumps(row))
    assert RecentWalkProbe(tmp_path, "test").observe(b"", {}, None) is None
