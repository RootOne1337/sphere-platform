
from types import SimpleNamespace
import unittest

import numpy as np

from motor_worker.route_roma_recovery import RomaVehicleLocalizer, _Seed


class RomaCurrentFrameTests(unittest.TestCase):
    def setUp(self):
        self.tracker = SimpleNamespace()
        self.tracker._last_ordinary = None
        self.tracker.last_source_sha = "current"
        reply = {0: (np.array([1]), np.array([[3., 4.]]))}
        self.tracker.roma_process = SimpleNamespace(poll=lambda: reply)
        self.points = np.arange(15.).reshape(5, 3)
        self.frame = SimpleNamespace(received_at=1.25, receiver_sequence=4)

    def queue(self, at=1., seq=3, sha="previous"):
        self.tracker._pending_roma = (seq, at, sha, "gray", None, ((10, self.points),))

    def test_completed_work_is_only_a_seed_for_newer_distinct_frame(self):
        self.queue()
        seed = RomaVehicleLocalizer._try_roma_seed(self.tracker, self.frame)
        self.assertEqual(seed.at, 1.)
        self.assertEqual(seed.pairs[0][0], 10)
        np.testing.assert_array_equal(seed.pairs[0][1], self.points[[1]])
        self.assertIsNone(self.tracker._pending_roma)

    def test_stale_duplicate_or_wrong_order_seed_is_discarded(self):
        for at, seq, sha in [(.4, 3, "old"), (1., 3, "current"), (1., 4, "old")]:
            with self.subTest(at=at, seq=seq, sha=sha):
                self.queue(at, seq, sha)
                self.assertIsNone(RomaVehicleLocalizer._try_roma_seed(self.tracker, self.frame))
                self.assertIsNone(self.tracker._pending_roma)

    def test_newer_ordinary_pose_prevents_late_gpu_vote(self):
        self.queue()
        self.tracker._last_ordinary = SimpleNamespace(received_at=1.05)
        self.assertIsNone(RomaVehicleLocalizer._try_roma_seed(self.tracker, self.frame))

    def test_old_anchor_is_discarded_before_any_flow(self):
        anchor = _Seed(0.3, 1., None, (), None)
        self.assertIsNone(RomaVehicleLocalizer._measure_seed(self.tracker, anchor, self.frame))


if __name__ == "__main__":
    unittest.main()
