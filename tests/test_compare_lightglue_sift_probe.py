import unittest

from scripts.pilot.compare_lightglue_sift_probe import compare


class CompareProbeTests(unittest.TestCase):
    def test_same_frames_and_reference_step(self):
        baseline = {
            "samples": [
                {
                    "source_index": 3,
                    "seconds": 0.5,
                    "retrieved_views": [0],
                    "views": {"0": {"pnp_passed": False}},
                }
            ]
        }
        candidate = {
            "samples": [
                {
                    "source_index": 3,
                    "seconds": 0.5,
                    "feature_ms": 10,
                    "candidates": [
                        {
                            "view": 0,
                            "pnp_passed": True,
                            "center": [0.5, 0, 0],
                            "inliers": 22,
                            "matching_ms": 5,
                            "verify_ms": 1,
                        }
                    ],
                }
            ]
        }
        geometry = {
            "cameras": [
                {"ticks_90k": 0, "center": [0, 0, 0]},
                {"ticks_90k": 90000, "center": [1, 0, 0]},
            ]
        }
        result = compare(baseline, candidate, geometry)
        self.assertEqual((result["classical_passes"], result["lightglue_passes"]), (0, 1))
        self.assertEqual(result["lightglue_disagreement_steps"]["max"], 0)
        self.assertFalse(result["ground_truth"])
        candidate["samples"][0]["candidates"].append(
            {
                "view": 1,
                "pnp_passed": True,
                "center": [4.0, 0, 0],
                "inliers": 20,
                "matching_ms": 5,
                "verify_ms": 1,
            }
        )
        baseline["samples"][0]["retrieved_views"].append(1)
        baseline["samples"][0]["views"]["1"] = {"pnp_passed": False}
        self.assertEqual(compare(baseline, candidate, geometry)["lightglue_ambiguous"], 1)
        candidate["samples"][0]["source_index"] = 4
        with self.assertRaisesRegex(ValueError, "probe_frames_mismatch"):
            compare(baseline, candidate, geometry)

    def test_center_jump_is_diagnostic_not_execution_qualification(self):
        base = []
        learned = []
        for i, center in enumerate(([0.0, 0, 0], [3.0, 0, 0])):
            base.append(
                {
                    "source_index": i,
                    "seconds": i * 0.2,
                    "retrieved_views": [0],
                    "views": {"0": {"pnp_passed": False}},
                }
            )
            learned.append(
                {
                    "source_index": i,
                    "seconds": i * 0.2,
                    "feature_ms": 1,
                    "candidates": [
                        {
                            "view": 0,
                            "pnp_passed": True,
                            "center": center,
                            "inliers": 22,
                            "matching_ms": 1,
                            "verify_ms": 1,
                        }
                    ],
                }
            )
        geometry = {
            "cameras": [
                {"ticks_90k": 0, "center": [0, 0, 0]},
                {"ticks_90k": 90000, "center": [1, 0, 0]},
            ]
        }
        result = compare({"samples": base}, {"samples": learned}, geometry)
        self.assertEqual(
            (result["consecutive_center_pairs"], result["center_pair_discontinuities"]), (1, 1)
        )
        self.assertFalse(result["execution_qualified"])


if __name__ == "__main__":
    unittest.main()
