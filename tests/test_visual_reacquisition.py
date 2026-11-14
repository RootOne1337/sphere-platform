import unittest

from motor_worker.visual_place import PlaceResult
from motor_worker.visual_reacquisition import LocalReacquisition


def match(index):
    return PlaceResult("matched", index, 60, "experimental")


class ReacquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tracker = LocalReacquisition((0.0, 0.5, 1.0, 1.5, 2.0, 8.0, 8.5), epoch="e")
        self.frame = 0
        self.at = 0.0

    def observe(self, result):
        self.frame += 1
        self.at += 0.2
        return self.tracker.observe(result, self.at, frame_id=self.frame, epoch="e")

    def test_missing_candidate_recovers_near_anchor_after_three_new_views(self):
        for i in (0, 1, 1):
            initial = self.observe(match(i))
        self.assertEqual((initial.state, initial.anchor), ("matched", 1))
        lost = self.observe(PlaceResult("unknown", None, 0, "missing"))
        self.assertEqual((lost.state, lost.reference, lost.anchor), ("unknown", None, 1))
        self.assertEqual(self.observe(match(2)).state, "confirming")
        self.assertEqual(self.observe(match(2)).state, "confirming")
        restored = self.observe(match(3))
        self.assertEqual((restored.state, restored.anchor), ("matched", 3))

    def test_repeated_far_false_match_never_teleports_anchor(self):
        for _ in range(3):
            self.observe(match(0))
        for _ in range(5):
            result = self.observe(match(5))
            self.assertEqual((result.state, result.reference, result.anchor), ("unknown", None, 0))
        for _ in range(3):
            result = self.observe(match(1))
        self.assertEqual((result.state, result.anchor), ("matched", 1))

    def test_initial_far_match_rejected_and_epoch_change_does_not_adopt(self):
        for _ in range(3):
            self.assertEqual(self.observe(match(5)).state, "unknown")
        result = self.tracker.observe(
            match(0), self.at + 0.2, frame_id=self.frame + 1, epoch="other"
        )
        self.assertEqual(result.reason, "capture_epoch_changed_or_missing")
        self.assertIsNone(result.anchor)

    def test_duplicate_and_clock_reversal_do_not_confirm(self):
        self.observe(match(0))
        duplicate = self.tracker.observe(match(0), self.at + 0.1, frame_id=self.frame, epoch="e")
        self.assertEqual(duplicate.reason, "source_frame_not_increasing")
        self.frame += 1
        old = self.tracker.observe(match(0), self.at - 0.1, frame_id=self.frame, epoch="e")
        self.assertEqual(old.reason, "observation_clock_not_increasing")
        self.assertEqual(self.observe(match(0)).state, "confirming")

    def test_invalid_candidate_clears_confirmation(self):
        self.observe(match(0))
        with self.assertRaises(ValueError):
            self.observe(match(99))
        self.assertEqual(self.observe(match(0)).state, "confirming")

    def test_long_loss_leaves_far_new_match_unknown_until_explicit_new_session(self):
        for _ in range(3):
            self.observe(match(0))
        for _ in range(25):
            self.observe(PlaceResult("unknown", None, 0, "long_loss"))
        for _ in range(5):
            result = self.observe(match(5))
            self.assertEqual((result.state, result.reference, result.anchor), ("unknown", None, 0))
        # Reinitialising deliberately starts a *different* observer; this does
        # not turn an unknown candidate into a trusted physical location.
        self.assertIsNone(LocalReacquisition((0.0, 0.5, 8.0, 8.5), epoch="new").anchor)
