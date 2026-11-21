import unittest

import numpy as np

from scripts.pilot.compare_learned_replay_geometry import merge_candidate_observations
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

    def test_measured_view_merge_drops_conflicts_and_excludes_unrelated_view(self):
        landmarks = np.r_[np.arange(30), np.arange(30), np.arange(30, 60)]
        arrays = {
            "offsets": np.array([0, 30, 60, 90]),
            "native_ids": landmarks,
            "xyz": np.column_stack((landmarks, landmarks, landmarks)),
        }
        measured = {
            0: (np.array([0, 1, 2, 3]), np.array([[0, 0], [1, 1], [2, 2], [3, 3]])),
            1: (np.array([30, 31, 34, 35]), np.array([[0, 0], [1, 2], [2, 2], [5, 5]])),
            2: (np.array([60]), np.array([[9, 9]])),
        }
        [(group, world, query)] = merge_candidate_observations(arrays, measured)
        self.assertEqual(group, [0, 1])
        np.testing.assert_array_equal(world[:, 0], [0, 3, 5])
        np.testing.assert_array_equal(query, [[0, 0], [3, 3], [5, 5]])


if __name__ == "__main__":
    unittest.main()
