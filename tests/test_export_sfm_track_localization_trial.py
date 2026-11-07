import unittest

from scripts.pilot.export_sfm_track_localization_trial import balanced_tracks


class BalancedTracksTest(unittest.TestCase):
    def test_cap_preserves_later_view_and_does_not_duplicate_track(self):
        candidates = [
            (9, "a", None, (0, 1)),
            (8, "b", None, (0,)),
            (7, "c", None, (0,)),
            (3, "tail", None, (2,)),
        ]
        chosen = balanced_tracks(candidates, 3, 2)
        self.assertEqual([row[1] for row in chosen], ["a", "tail"])

    def test_empty_and_invalid_view(self):
        self.assertEqual(balanced_tracks([], 3, 5), [])
        with self.assertRaisesRegex(ValueError, "sfm_track_view_invalid"):
            balanced_tracks([(3, "bad", None, (3,))], 3, 1)


if __name__ == "__main__":
    unittest.main()
