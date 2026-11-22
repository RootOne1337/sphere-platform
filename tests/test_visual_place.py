"""CPU-only checks of the experimental visual-place retrieval contract."""

import importlib.util
import unittest
from unittest.mock import patch

from motor_worker.visual_global_recovery import GlobalRecovery
from motor_worker.visual_place import VisualPlaceIndex, select_place_candidates


@unittest.skipUnless(
    all(importlib.util.find_spec(x) for x in ("cv2", "numpy")), "vision dependencies required"
)
class VisualPlaceTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        cv2.setNumThreads(2)
        cv2.setRNGSeed(17)
        rng = np.random.default_rng(190)
        self.scene = rng.integers(0, 256, (540, 960, 3), dtype=np.uint8)
        self.other = rng.integers(0, 256, (540, 960, 3), dtype=np.uint8)

    def test_shifted_scene_matches_but_blank_and_unrelated_are_unknown(self):
        index = VisualPlaceIndex(max_candidates=2)
        index.add(self.scene, 0.0)
        index.add(self.other, 1.0)
        shifted = self.cv.warpAffine(
            self.scene, self.np.float32([[1, 0, 25], [0, 1, 0]]), (960, 540)
        )
        result = index.compare(shifted)
        self.assertEqual((result.state, result.reference), ("matched", 0))
        self.assertGreaterEqual(result.inliers, 15)
        self.assertEqual(index.compare(self.np.zeros_like(self.scene)).state, "unknown")
        unrelated = self.np.random.default_rng(191).integers(
            0, 256, self.scene.shape, dtype=self.np.uint8
        )
        self.assertEqual(index.compare(unrelated).state, "unknown")

    def test_identical_distant_views_are_ambiguous(self):
        index = VisualPlaceIndex(max_candidates=2)
        index.add(self.scene, 0.0)
        index.add(self.scene, 3.0)
        result = index.compare(self.scene)
        self.assertEqual(result.state, "ambiguous")
        self.assertIsNone(result.reference)

    def test_candidate_output_preserves_ambiguous_distant_views(self):
        index = VisualPlaceIndex(max_candidates=2)
        index.add(self.scene, 0.0)
        index.add(self.scene, 3.0)
        hypotheses = index.compare_candidates(self.scene)
        self.assertEqual(hypotheses.state, "candidates")
        self.assertEqual({result.reference for result in hypotheses.candidates}, {0, 1})
        self.assertTrue(
            all(
                result.state == "matched" and result.inliers >= 15
                for result in hypotheses.candidates
            )
        )
        self.assertEqual(index.compare(self.scene).state, "ambiguous")

    def test_geometric_candidates_feed_global_recovery_without_hiding_aliases(self):
        index = VisualPlaceIndex(max_candidates=4)
        for seconds in (0.0, 0.5, 8.0, 8.5):
            index.add(self.scene, seconds)
        recovery = GlobalRecovery((0.0, 0.5, 8.0, 8.5), epoch="test")
        # Each fresh source ID contains an identical query. Nearby candidate
        # identities vary, but the pixels are deliberately not independent:
        # this checks alias preservation, never live confidence or motion.
        for frame_id in range(1, 5):
            candidates = index.compare_candidates(self.scene)
            result = recovery.observe(
                candidates.candidates, frame_id * 0.2, frame_id=frame_id, epoch="test"
            )
        self.assertEqual(result.state, "ambiguous")
        self.assertIsNone(result.reference)
        self.assertTrue(any(index_ < 2 for index_ in result.surviving))
        self.assertTrue(any(index_ >= 2 for index_ in result.surviving))

    def test_blank_returns_no_candidate_not_a_fake_match(self):
        index = VisualPlaceIndex(max_candidates=2)
        index.add(self.scene, 0.0)
        index.add(self.other, 1.0)
        result = index.compare_candidates(self.np.zeros_like(self.scene))
        self.assertEqual((result.state, result.candidates), ("unknown", ()))

    def test_diversity_can_expose_a_hidden_distant_duplicate(self):
        index = VisualPlaceIndex(max_candidates=4)
        for seconds in (0.0, 4.0, 4.1, 4.2, 4.3):
            index.add(self.scene, seconds)
        ranked = index.compare_candidates(self.scene)
        diverse = index.compare_candidates(self.scene, strategy="diverse")
        self.assertNotIn(0, {c.reference for c in ranked.candidates})
        self.assertIn(0, {c.reference for c in diverse.candidates})
        self.assertEqual(len(diverse.candidates), 4)
        # Default API keeps its original ranking semantics.
        self.assertEqual(index.compare(self.scene).state, "matched")
        # Preserve the distant possibility through the sequence layer too.
        tracker = GlobalRecovery((0.0, 4.0, 4.1, 4.2, 4.3), epoch="synthetic")
        for frame_id in range(1, 5):
            candidates = index.compare_candidates(self.scene, strategy="diverse")
            result = tracker.observe(
                candidates.candidates, frame_id * 0.2, frame_id=frame_id, epoch="synthetic"
            )
        self.assertEqual(result.state, "ambiguous")
        self.assertIsNone(result.reference)

    def test_candidate_selection_is_bounded_and_validates_inputs(self):
        ranked, times = (4, 3, 2, 1, 0), (0.0, 4.0, 4.1, 4.2, 4.3)
        self.assertEqual(select_place_candidates(ranked, times, 4), (4, 3, 2, 1))
        self.assertEqual(
            select_place_candidates(ranked, times, 4, strategy="diverse"), (4, 3, 0, 2)
        )
        self.assertEqual(select_place_candidates((1, 0), (0.0, 1.0), 4, strategy="diverse"), (1, 0))
        with self.assertRaises(ValueError):
            select_place_candidates((0, 0), (0.0, 1.0), 2, strategy="diverse")
        with self.assertRaises(ValueError):
            select_place_candidates((0, 1), (1.0, 0.0), 2, strategy="diverse")
        with self.assertRaises(ValueError):
            select_place_candidates((0, 1), (0.0, 1.0), 2, strategy=[])

    def test_reflected_or_collapsed_homography_is_rejected(self):
        index = VisualPlaceIndex(max_candidates=2)
        index.add(self.scene, 0.0)
        index.add(self.other, 1.0)
        real = self.cv.findHomography
        for invalid in (
            self.np.float64([[-1, 0, 960], [0, 1, 0], [0, 0, 1]]),
            self.np.float64([[0.1, 0, 0], [0, 0.1, 0], [0, 0, 1]]),
        ):

            def forced(*args, **kwargs):
                _, mask = real(*args, **kwargs)
                return invalid, mask

            with (
                self.subTest(transform=invalid.tolist()),
                patch.object(self.cv, "findHomography", side_effect=forced),
            ):
                self.assertEqual(index.compare(self.scene).state, "unknown")

    def test_bad_inputs_and_unordered_references_are_rejected(self):
        for bad in (True, 1, 17):
            with self.assertRaises(ValueError):
                VisualPlaceIndex(max_candidates=bad)
        index = VisualPlaceIndex()
        index.add(self.scene, 1.0)
        with self.assertRaises(ValueError):
            index.add(self.scene, 1.0)
        with self.assertRaises(ValueError):
            index.add(self.scene, float("nan"))
        with self.assertRaises(ValueError):
            index.add(self.scene[:, :, 0], 2.0)
        with self.assertRaisesRegex(ValueError, "place_aspect_ratio_changed"):
            index.add(self.scene[:, :500], 2.0)
        with self.assertRaises(ValueError):
            index.compare(self.scene)
