import unittest
from types import SimpleNamespace

from scripts.pilot.reconstruct_saved_graph_trial import verify_fixed_focal


class FixedFocalVerificationTests(unittest.TestCase):
    def test_detects_any_changed_or_nonfinite_camera(self):
        verify_fixed_focal((SimpleNamespace(params=[605.186]),), 605.186)
        for value in (589.9, float("nan"), float("inf")):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(RuntimeError, "fixed_focal_not_preserved"),
            ):
                verify_fixed_focal(
                    (SimpleNamespace(params=[605.186]), SimpleNamespace(params=[value])), 605.186
                )

    def test_requires_valid_nonempty_cameras(self):
        with self.assertRaisesRegex(ValueError, "fixed_focal_invalid"):
            verify_fixed_focal((), 605.0)
        with self.assertRaisesRegex(ValueError, "fixed_focal_invalid"):
            verify_fixed_focal((SimpleNamespace(params=[1]),), float("nan"))


if __name__ == "__main__":
    unittest.main()
