import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = np = None

from motor_worker.visual_servo_epipolar_diagnostic import compare_epipolar


@unittest.skipIf(cv2 is None, "opencv unavailable")
class EpipolarDiagnosticTests(unittest.TestCase):
    def test_distinct_textured_patches_at_different_displacements(self):
        # A simple multi-depth-like image fixture, not a simulated vehicle or
        # evidence that estimated motion corresponds to a steering command.
        rng = np.random.default_rng(32)
        reference = np.zeros((540, 960, 3), dtype=np.uint8)
        query = np.zeros_like(reference)
        for y in (90, 170, 250, 330):
            for x in (70, 190, 310, 430, 550, 670, 790, 880):
                patch = rng.integers(0, 256, (35, 35, 3), dtype=np.uint8)
                dx = int(rng.integers(5, 25))
                reference[y : y + 35, x : x + 35] = patch
                query[y : y + 35, x + dx : x + dx + 35] = patch
        result = compare_epipolar(reference, query)
        self.assertEqual(result.state, "measured")
        self.assertGreaterEqual(result.inliers, 20)
        self.assertEqual(result.reason, "epipolar_correspondence_not_pose")

    def test_untextured_is_unknown(self):
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        result = compare_epipolar(image, image)
        self.assertEqual(result.state, "unknown")
        self.assertIsNone(result.x_pixels)

    def test_rejects_wrong_size(self):
        with self.assertRaises(ValueError):
            compare_epipolar(
                np.zeros((100, 100, 3), dtype=np.uint8), np.zeros((540, 960, 3), dtype=np.uint8)
            )
