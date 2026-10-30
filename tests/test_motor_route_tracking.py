"""Anchored tracking must re-solve map geometry, never coast across lost pixels."""

import hashlib
import importlib.util
import unittest
from dataclasses import replace

from motor_worker.landmarks import RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.route_localization import SparseRoute, pipeline_id
from motor_worker.route_tracking import AnchoredRouteLocalizer

AVAILABLE = all(importlib.util.find_spec(m) for m in ("cv2", "numpy"))
EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
EPISODE = "f3867238-d651-4ce0-9e71-e892ce6e28fb"
GOAL = "7be1db61-acab-4c6b-8bea-b5330594fdcf"


@unittest.skipUnless(AVAILABLE, "optional CPU vision dependencies required")
class AnchoredTrackingTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        rng = np.random.default_rng(422)
        self.xyz = rng.uniform([-8, -5, 15], [8, 5, 35], (180, 3))
        self.descriptors = rng.uniform(0, 1, (180, 128)).astype("<f4")
        self.descriptors /= np.linalg.norm(self.descriptors, axis=1, keepdims=True)
        route = SparseRoute(EPOCH, GOAL, "a"*64, pipeline_id(),
            RouteViewProfile(GOAL, 960, 540, (0, 0, 1, 1), ((.99, .99, 1, 1),)),
            (450., 450., 480., 270.), tuple(tuple(map(float, row)) for row in self.xyz), self.descriptors.tobytes(),
            tuple((0., 0., float(z)) for z in range(0, 36, 5)), tuple(map(float, range(8))),
            tuple(hashlib.sha256(str(t).encode()).hexdigest() for t in range(8)),
            (tuple(range(8)),)*180, "b"*64, tuple(range(8)))
        self.now, self.index = 10., 0
        self.tracker = AnchoredRouteLocalizer(route, capture_epoch=EPOCH, episode_id=EPISODE,
                                             goal_revision=GOAL, clock=lambda: self.now)
        self.patches = rng.integers(40, 255, (180, 11, 11, 3), np.uint8)
        self.pixels = None
        self.global_calls = 0

        def extract():
            self.global_calls += 1
            return self.pixels, self.descriptors

        # Exact descriptor matches isolate tracking/PnP. Real-video comparison
        # separately exercises the actual SIFT extractor on untaught frames.
        self.tracker._extract = extract

    def observe(self, *, blank=False, **kwargs):
        self.now += .2
        self.index += 1
        center = self.np.array([self.index*.012, 0., 5.])
        self.pixels = self.cv.projectPoints(self.xyz, self.np.zeros(3), -center,
                                            self.tracker.K, None)[0].reshape(-1, 2)
        image = self.np.zeros((540, 960, 3), self.np.uint8)
        if not blank:
            for patch, (x, y) in zip(self.patches, self.np.rint(self.pixels).astype(int)):
                image[y-5:y+6, x-5:x+6] = patch
        frame = PolicyFrame(EPOCH, self.index, self.now, 960, 540, image.tobytes())
        self.last_frame = frame
        pose = self.tracker.observe(frame, episode_id=EPISODE, goal_revision=GOAL,
                                    scene=kwargs.get("scene", "active"))
        return pose, center

    def confirm(self):
        for i in range(3):
            pose, _ = self.observe()
            self.assertEqual(pose.state, "localized" if i == 2 else "confirming")
            self.assertEqual(self.tracker.last_diagnostic["method"], "descriptor_pnp")

    def test_actual_lk_and_pnp_follow_existing_landmarks_without_new_descriptors(self):
        self.confirm()
        pose, center = self.observe()
        self.assertEqual(self.tracker.last_diagnostic["method"], "map_anchored_flow")
        self.assertEqual(self.global_calls, 3)
        self.assertEqual(pose.state, "localized")
        self.assertGreater(pose.inliers, 100)
        self.np.testing.assert_allclose(pose.center, center, atol=.04)
        self.assertLessEqual(len(self.tracker._anchors[2]), 256)

    def test_repeated_rgb_discards_anchors_and_requires_fresh_confirmation(self):
        self.confirm()
        self.now += .2
        self.index += 1
        duplicate = replace(self.last_frame, receiver_sequence=self.index, received_at=self.now)
        pose = self.tracker.observe(duplicate, episode_id=EPISODE, goal_revision=GOAL, scene="active")
        self.assertEqual((pose.state, pose.reason), ("unknown", "route_repeated_rgb_not_independent"))
        self.assertIsNone(self.tracker._anchors)
        self.assertIsNone(self.tracker._descriptor_at)
        self.assertEqual(self.tracker.last_diagnostic["method"], "not_attempted")
        self.confirm()

    def test_mandatory_global_failure_cannot_fall_back_to_flow(self):
        self.confirm()
        self.tracker._descriptor_at = self.now-.81
        self.tracker._extract = lambda: (self.np.empty((0, 2)), self.np.empty((0, 128), self.np.float32))
        self.tracker._flow = lambda: self.fail("expired anchors must not be tried")
        pose, _ = self.observe()
        self.assertEqual(pose.state, "unknown")
        self.assertIsNone(self.tracker._anchors)
        self.assertIsNone(self.tracker._descriptor_at)

    def test_full_occlusion_clears_anchors_and_needs_global_reconfirmation(self):
        self.confirm()
        old_extract = self.tracker._extract
        self.tracker._extract = lambda: (self.np.empty((0, 2)), self.np.empty((0, 128), self.np.float32))
        pose, _ = self.observe(blank=True)
        self.assertEqual(pose.reason, "route_pose_not_verified")
        self.assertIsNone(self.tracker._anchors)
        self.tracker._extract = old_extract
        self.confirm()

    def test_flow_rejects_backward_inconsistent_correspondences(self):
        from unittest.mock import patch

        self.confirm()
        original = self.cv.calcOpticalFlowPyrLK
        calls = 0

        def corrupt(*args, **kwargs):
            nonlocal calls
            points, status, error = original(*args, **kwargs)
            calls += 1
            if calls == 2:
                points += 10
            return points, status, error

        with patch.object(self.cv, "calcOpticalFlowPyrLK", side_effect=corrupt):
            pose, _ = self.observe()
        self.assertEqual(pose.state, "localized")
        self.assertEqual(self.tracker.last_diagnostic["flowRetained"], 0)
        self.assertEqual(self.tracker.last_diagnostic["method"], "descriptor_pnp")
        self.assertEqual(self.global_calls, 4)

    def test_gap_and_menu_discard_anchors_without_attempting_tracking(self):
        for scene in ("menu", "active"):
            self.tracker.confirmations = 0
            self.confirm()
            if scene == "active":
                self.now += .6
            pose, _ = self.observe(scene=scene)
            self.assertEqual(pose.state, "unknown")
            self.assertIsNone(self.tracker._anchors)
            self.assertEqual(self.tracker.last_diagnostic["method"], "not_attempted")

    def test_expiry_during_flow_clears_all_tracking_state(self):
        self.confirm()
        original = self.tracker._flow

        def slow():
            result = original()
            self.now += .26
            return result

        self.tracker._flow = slow
        pose, _ = self.observe()
        self.assertEqual(pose.reason, "route_frame_expired_during_localization")
        self.assertIsNone(self.tracker._anchors)
        self.assertEqual(self.tracker.confirmations, 0)

    def test_failed_calculation_does_not_retain_rgb_or_previous_tracking(self):
        self.confirm()

        def fail():
            raise RuntimeError("fixture_calculation_failed")

        self.tracker._flow = fail
        with self.assertRaisesRegex(RuntimeError, "fixture_calculation_failed"):
            self.observe()
        for value in (self.tracker._anchors, self.tracker._descriptor_at, self.tracker._frame,
                      self.tracker._gray, self.tracker._solution, self.tracker.previous):
            self.assertIsNone(value)
        self.assertEqual(self.tracker.confirmations, 0)

    def test_wide_recovery_is_bounded_and_returns_to_small_shortlist_after_confirmation(self):
        from unittest.mock import patch
        from motor_worker.route_localization import RouteLocalizer
        from motor_worker.protocol import ProtocolError

        self.tracker.recovery_candidate_limit = 8
        seen = []
        original = RouteLocalizer._solve

        def solve(localizer, *args):
            seen.append(localizer.candidate_limit)
            return original(localizer, *args)

        with patch.object(RouteLocalizer, '_solve', solve):
            self.confirm()
            self.tracker._descriptor_at = self.now-.81
            pose, _ = self.observe()
        self.assertEqual(pose.state, 'localized')
        self.assertEqual(seen, [8, 8, 8, 3])
        self.assertEqual(self.tracker.candidate_limit, 3)
        for invalid in (True, 2, 9):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ProtocolError, 'invalid_route_recovery_candidate_limit'):
                AnchoredRouteLocalizer(self.tracker.route, capture_epoch=EPOCH, episode_id=EPISODE,
                                       goal_revision=GOAL, recovery_candidate_limit=invalid)

    def test_failed_wide_retrieval_restores_config_and_revokes_tracking(self):
        from unittest.mock import patch
        self.tracker.recovery_candidate_limit = 8
        with patch('motor_worker.route_localization.RouteLocalizer._solve', side_effect=RuntimeError('fixture_retrieval')):
            with self.assertRaisesRegex(RuntimeError, 'fixture_retrieval'):
                self.observe()
        self.assertEqual(self.tracker.candidate_limit, 3)
        self.assertIsNone(self.tracker.previous)
        self.assertIsNone(self.tracker._anchors)
