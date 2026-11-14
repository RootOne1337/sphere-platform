import unittest

from scripts.pilot.diagnose_keyframe_2d3d import unique_correspondences


class KeyframeProbeTests(unittest.TestCase):
    def test_correspondences_are_one_to_one_and_keep_best_distance(self):
        pairs = [
            (0.30, 1, 10),
            (0.10, 1, 11),
            (0.20, 2, 11),
            (0.40, 2, 12),
            (0.05, 3, 13),
            (0.25, 3, 13),
        ]
        self.assertEqual(unique_correspondences(pairs), [(3, 13), (1, 11), (2, 12)])

    def test_empty_correspondences(self):
        self.assertEqual(unique_correspondences([]), [])


if __name__ == "__main__":
    unittest.main()
