import unittest

from scripts.pilot.compare_covisibility_jumps import compare


class CovisibilityJumpComparisonTests(unittest.TestCase):
    def test_compares_previous_pose_and_keeps_control_disabled(self):
        baseline = {
            "independent_pass": False,
            "physical_actions": 0,
            "samples": [
                {
                    "source_index": 1,
                    "seconds": 1.0,
                    "lightglue_unambiguous_candidate": True,
                    "lightglue_center": [0, 0, 0],
                },
                {"source_index": 2, "seconds": 1.2, "center_pair_discontinuity": True},
            ],
        }
        groups = {
            "same_capture": True,
            "physical_actions": 0,
            "samples": [
                {
                    "source_index": 2,
                    "seconds": 1.2,
                    "groups": [{"pnp_passed": True, "inliers": 30, "center": [0.5, 0, 0]}],
                }
            ],
        }
        geometry = {"cameras": [{"center": [0, 0, 0]}, {"center": [1, 0, 0]}]}
        result = compare(groups, baseline, geometry)
        self.assertEqual((result["group_pnp_count"], result["within_motion_limit_count"]), (1, 1))
        self.assertFalse(result["execution_qualified"])
        groups["samples"][0]["seconds"] = 2.0
        with self.assertRaisesRegex(ValueError, "covisibility_compare_pair_invalid"):
            compare(groups, baseline, geometry)


if __name__ == "__main__":
    unittest.main()
