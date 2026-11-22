import unittest

import numpy as np

from scripts.pilot.compare_remapped_sfm_correspondences import fit_similarity


class SimilarityAlignmentTests(unittest.TestCase):
    def test_known_scale_rotation_and_translation(self):
        src = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
        expected = (2 * (rotation @ src.T)).T + np.array([4, 5, 6])
        scale, R, t = fit_similarity(src, expected)
        np.testing.assert_allclose((scale * (R @ src.T)).T + t, expected, atol=1e-8)

    def test_rejects_degenerate_and_nonfinite_alignment(self):
        with self.assertRaisesRegex(ValueError, "alignment_degenerate"):
            fit_similarity(
                [[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]],
                [[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]],
            )
        with self.assertRaisesRegex(ValueError, "alignment_invalid"):
            fit_similarity(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [float("nan"), 0, 1]],
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
            )


if __name__ == "__main__":
    unittest.main()
