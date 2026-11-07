import unittest
from unittest.mock import patch

from scripts.pilot.audit_sfm_pairs_lightweight import inspect, memory_checkpoint


class PairDiagnosticTests(unittest.TestCase):
    def test_memory_floor_refuses_low_physical_or_commit_space(self):
        for values in (
            {
                "availableRamBytes": 3 * 2**30,
                "commitLimitBytes": 10 * 2**30,
                "committedBytes": 2 * 2**30,
            },
            {
                "availableRamBytes": 8 * 2**30,
                "commitLimitBytes": 10 * 2**30,
                "committedBytes": 7 * 2**30,
            },
        ):
            with (
                self.subTest(values=values),
                patch(
                    "scripts.pilot.audit_sfm_pairs_lightweight.windows_memory", return_value=values
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "lightweight_diagnostic_memory_low"):
                    memory_checkpoint()

    def test_textured_identical_images_have_homography_support(self):
        import cv2
        import numpy as np

        cv2.setNumThreads(1)
        image = np.random.default_rng(17).integers(0, 256, (540, 960, 3), dtype=np.uint8)
        for method in ("orb", "sift"):
            result = inspect(image, image, method)
            self.assertGreaterEqual(result["homography_inliers"], 20)
            self.assertGreaterEqual(result["homography_occupied_cells"], 4)
