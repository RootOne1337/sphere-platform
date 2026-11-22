import unittest

from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import PlaceResult


def match(index):
    return PlaceResult("matched", index, 50, "test")


class GlobalRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.recovery = GlobalRecovery((0.0, 0.5, 1.0, 8.0, 8.5, 9.0), epoch="e")
        self.frame = 0
        self.time = 0.0

    def observe(self, *indices):
        self.frame += 1
        self.time += 0.2
        return self.recovery.observe(
            tuple(map(match, indices)), self.time, frame_id=self.frame, epoch="e"
        )

    def test_one_repeated_view_alone_never_confirms(self):
        for _ in range(8):
            self.assertEqual(self.observe(0).state, "confirming")

    def test_four_fresh_coherent_views_produce_only_a_hypothesis(self):
        for i in (0, 1, 1):
            self.assertEqual(self.observe(i).state, "confirming")
        result = self.observe(2)
        self.assertEqual((result.state, result.reference), ("hypothesis", 2))
        self.assertEqual(result.reason, "image_sequence_not_pose_or_control")

    def test_repeated_reference_and_map_tail_are_diagnostic_only(self):
        for i in (3, 4, 4):
            self.observe(i)
        first = self.observe(5)
        self.assertEqual(
            (first.state, first.reference_streak, first.near_reference_tail),
            ("hypothesis", 1, True),
        )
        repeated = self.observe(5)
        self.assertEqual(repeated.reference_streak, 2)
        self.assertAlmostEqual(repeated.reference_streak_seconds, 0.2)
        self.assertEqual(self.observe().state, "unknown")
        self.assertEqual(self.observe(5).reference_streak, 0)

    def test_distant_competing_sequences_remain_ambiguous(self):
        for pair in ((0, 3), (1, 4), (1, 4)):
            self.observe(*pair)
        result = self.observe(2, 5)
        self.assertEqual((result.state, result.reference), ("ambiguous", None))
        self.assertEqual(result.surviving, (2, 5))

    def test_sparse_distant_competitor_cannot_disappear_from_decision(self):
        for pair in ((0, 3), (1, 3), (1, 3)):
            self.observe(*pair)
        result = self.observe(2, 3)
        self.assertEqual((result.state, result.reference), ("ambiguous", None))
        self.assertIn(3, result.surviving)

    def test_one_missing_distant_competitor_still_blocks_premature_choice(self):
        for pair in ((0, 3), (1, 4), (1, 4)):
            self.observe(*pair)
        result = self.observe(2)
        self.assertEqual((result.state, result.reference), ("ambiguous", None))
        self.assertEqual(result.surviving, (2, 4))
        self.assertEqual(result.held_previous, (4,))
        # An absent competitor is not counted as a new matching observation.
        result = self.observe(2)
        self.assertEqual(result.state, "hypothesis")

    def test_present_adjacent_reference_is_not_a_missing_competitor(self):
        for i in (0, 1, 1):
            self.observe(i)
        self.assertEqual(self.observe(2).state, "hypothesis")

    def test_empty_duplicate_epoch_and_invalid_data_clear_history(self):
        for i in (0, 1, 1):
            self.observe(i)
        self.assertEqual(self.observe().state, "unknown")
        self.assertEqual(self.observe(2).state, "confirming")
        duplicate = self.recovery.observe(
            (match(2),), self.time + 0.1, frame_id=self.frame, epoch="e"
        )
        self.assertEqual(duplicate.reason, "source_frame_not_increasing")
        changed = self.recovery.observe(
            (match(2),), self.time + 0.2, frame_id=self.frame + 1, epoch="new"
        )
        self.assertEqual(changed.reason, "capture_epoch_changed_or_missing")
        with self.assertRaises(ValueError):
            self.recovery.observe((match(99),), self.time + 0.3, frame_id=self.frame + 2, epoch="e")

    def test_jump_cannot_inherit_confirmation(self):
        for i in (0, 1, 1):
            self.observe(i)
        self.assertEqual(self.observe(3).state, "confirming")

    def test_rejects_candidate_overflow_without_silently_discarding_competitors(self):
        tracker = GlobalRecovery(tuple(float(i) for i in range(12)), epoch="e")
        with self.assertRaisesRegex(ValueError, "invalid_global_recovery_observation"):
            tracker.observe(tuple(match(i) for i in range(9)), 0.1, frame_id=1, epoch="e")
        self.assertEqual(
            tracker.observe((match(0),), 0.2, frame_id=2, epoch="e").state, "confirming"
        )
