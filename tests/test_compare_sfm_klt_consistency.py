import unittest

from scripts.pilot.compare_sfm_klt_consistency import summarize


class KltConsistencySummaryTests(unittest.TestCase):
    def test_summarizes_missing_and_inlier_measurements_separately(self):
        rows = [
            {"models": {"a": {"median_px": 2.0, "median_ransac_inliers_px": 1.0}}},
            {"models": {"a": {"median_px": 6.0, "median_ransac_inliers_px": None}}},
            {"models": {}},
        ]
        result = summarize(rows, ["a", "missing"])
        self.assertEqual(result["a"]["pairs"], 2)
        self.assertEqual(result["a"]["median_of_pair_medians_px"], 4.0)
        self.assertEqual(result["a"]["ransac_pairs"], 1)
        self.assertEqual(result["a"]["ransac_inliers_median_of_pair_medians_px"], 1.0)
        self.assertIsNone(result["missing"]["p90_pair_median_px"])


if __name__ == "__main__":
    unittest.main()
