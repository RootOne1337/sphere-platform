import unittest

from motor_worker.visual_place import PlaceResult
from motor_worker.visual_place_sequence import VisualPlaceSequence


def match(index):
    return PlaceResult("matched", index, 50, "image_resemblance_not_pose")


class VisualPlaceSequenceTests(unittest.TestCase):
    def setUp(self):
        self.sequence = VisualPlaceSequence((0.0, 1.0, 2.0, 10.0, 11.0), epoch="episode-a")
        self.frame_id = 0

    def observe(self, result, at):
        self.frame_id += 1
        return self.sequence.observe(result, at, frame_id=self.frame_id, epoch="episode-a")

    def test_three_nearby_views_confirm_even_if_reference_advances(self):
        self.assertEqual(self.observe(match(0), 0.2).state, "confirming")
        self.assertEqual(self.observe(match(1), 0.4).state, "confirming")
        result = self.observe(match(2), 0.6)
        self.assertEqual((result.state, result.reference), ("matched", 2))
        self.assertEqual(result.reason, "image_sequence_not_pose_or_clearance")

    def test_uncertainty_and_gap_discard_prior_confirmation(self):
        for at in (0.1, 0.2, 0.3):
            self.observe(match(0), at)
        self.assertEqual(
            self.observe(PlaceResult("ambiguous", None, 30, "alias"), 0.4).state, "unknown"
        )
        self.assertEqual(self.observe(match(0), 0.5).state, "confirming")
        self.assertEqual(self.observe(match(0), 1.2).reason, "observation_gap")
        self.assertEqual(self.observe(match(0), 1.3).state, "confirming")

    def test_large_jump_does_not_confirm_new_place(self):
        for at in (0.1, 0.2, 0.3):
            self.observe(match(0), at)
        result = self.observe(match(3), 0.4)
        self.assertEqual(
            (result.state, result.reference, result.reason), ("unknown", None, "reference_jump")
        )
        self.assertEqual(self.observe(match(3), 0.5).state, "confirming")

    def test_clock_order_and_malformed_references_cannot_keep_lock(self):
        self.observe(match(0), 0.3)
        self.assertEqual(self.observe(match(0), 0.2).reason, "observation_clock_not_increasing")
        self.assertEqual(self.observe(match(0), 0.4).state, "confirming")
        with self.assertRaises(ValueError):
            self.observe(match(99), 0.5)
        with self.assertRaises(ValueError):
            VisualPlaceSequence((0.0, 0.0), epoch="episode-a")

    def test_invalid_match_clears_existing_lock(self):
        for at in (0.1, 0.2, 0.3):
            self.observe(match(0), at)
        with self.assertRaises(ValueError):
            self.observe(match(99), 0.4)
        self.assertEqual(self.observe(match(0), 0.5).state, "confirming")

    def test_repeated_or_older_source_frame_cannot_confirm(self):
        self.assertEqual(
            self.sequence.observe(match(0), 0.1, frame_id=10, epoch="episode-a").state, "confirming"
        )
        self.assertEqual(
            self.sequence.observe(match(0), 0.2, frame_id=10, epoch="episode-a").reason,
            "source_frame_not_increasing",
        )
        self.assertEqual(
            self.sequence.observe(match(0), 0.3, frame_id=9, epoch="episode-a").reason,
            "source_frame_not_increasing",
        )
        self.assertEqual(
            self.sequence.observe(match(0), 0.4, frame_id=11, epoch="episode-a").state, "confirming"
        )

    def test_clock_rollback_cannot_reacquire_at_old_time(self):
        self.sequence.observe(match(0), 10.0, frame_id=1, epoch="episode-a")
        for frame, at in enumerate((1.0, 1.1, 1.2), start=2):
            self.assertEqual(
                self.sequence.observe(match(0), at, frame_id=frame, epoch="episode-a").reason,
                "observation_clock_not_increasing",
            )
        self.assertEqual(
            self.sequence.observe(match(0), 10.1, frame_id=4, epoch="episode-a").reason,
            "source_frame_not_increasing",
        )
        self.assertEqual(
            self.sequence.observe(match(0), 10.1, frame_id=5, epoch="episode-a").state, "confirming"
        )

    def test_malformed_match_or_missing_frame_id_resets(self):
        for at in (0.1, 0.2, 0.3):
            self.observe(match(0), at)
        with self.assertRaises(ValueError):
            self.observe(PlaceResult("matched", 0, 0, "bad"), 0.4)
        self.assertEqual(self.observe(match(0), 0.5).state, "confirming")
        with self.assertRaises(ValueError):
            self.sequence.observe(match(0), 0.6)
        self.assertEqual(self.observe(match(0), 0.7).state, "confirming")

    def test_epoch_change_clears_confirmation_without_adopting_new_stream(self):
        for at in (0.1, 0.2, 0.3):
            self.observe(match(0), at)
        changed = self.sequence.observe(match(0), 0.4, frame_id=4, epoch="episode-b")
        self.assertEqual(
            (changed.state, changed.reason), ("unknown", "capture_epoch_changed_or_missing")
        )
        self.assertEqual(self.observe(match(0), 0.5).state, "confirming")
