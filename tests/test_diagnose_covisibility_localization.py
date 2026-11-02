import unittest

from scripts.pilot.diagnose_covisibility_localization import covisibility_groups, unique_votes


class CovisibilityTests(unittest.TestCase):
    def test_connected_components_and_invalid_views(self):
        tracks = {0: {1, 2}, 1: {2, 3}, 2: {5}, 3: {3, 6}}
        self.assertEqual(covisibility_groups([0, 1, 2, 3], tracks), [(0, 1, 3), (2,)])
        with self.assertRaisesRegex(ValueError, "covisibility_views_invalid"):
            covisibility_groups([0, 0], tracks)

    def test_ambiguous_votes_dropped_and_landmark_not_double_counted(self):
        rows = [(0, 10, 1), (1, 10, 1), (0, 11, 2), (1, 12, 2), (0, 10, 3), (0, 20, 4)]
        self.assertEqual(unique_votes(rows), [(1, 10, 2), (4, 20, 1)])


if __name__ == "__main__":
    unittest.main()
