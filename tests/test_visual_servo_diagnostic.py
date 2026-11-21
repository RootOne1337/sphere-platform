import unittest

try:
    import cv2 as cv
    import numpy as np
except ImportError:
    cv = np = None

from motor_worker.visual_servo_diagnostic import compare


@unittest.skipIf(cv is None, "opencv unavailable")
class ImageDisplacementTests(unittest.TestCase):
    def test_known_image_shift_is_not_pose(self):
        rng = np.random.default_rng(71)
        image = rng.integers(0, 256, (540, 960, 3), dtype=np.uint8)
        for shift in (-24, 24):
            moved = cv.warpAffine(image, np.float32([[1, 0, shift], [0, 1, 0]]), (960, 540))
            result = compare(image, moved)
            self.assertEqual(result.state, "measured")
            self.assertAlmostEqual(result.x_pixels, -shift, delta=2)
            self.assertAlmostEqual(result.center_x_pixels, -shift, delta=2)
            self.assertEqual(result.reason, "image_shift_only_not_pose")

    def test_untextured_is_unknown(self):
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        result = compare(image, image)
        self.assertEqual(result.state, "unknown")
        self.assertIsNone(result.x_pixels)

    def test_rejects_wrong_size(self):
        with self.assertRaises(ValueError):
            compare(
                np.zeros((100, 100, 3), dtype=np.uint8), np.zeros((540, 960, 3), dtype=np.uint8)
            )
