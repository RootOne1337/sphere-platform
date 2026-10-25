"""Known 3D geometry exercises actual descriptor matching and OpenCV PnP.

Image extraction is isolated in state tests; a separate real-video probe tests
the full extractor. Synthetic metric coordinates do not calibrate a game map.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from motor_worker.landmarks import RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError
from motor_worker.route_localization import (
    RouteLocalizer,
    SparseRoute,
    map_support,
    pipeline_id,
    render_guidance,
)

AVAILABLE = all(importlib.util.find_spec(m) for m in ("cv2", "numpy"))
EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
EPISODE = "f3867238-d651-4ce0-9e71-e892ce6e28fb"
GOAL = "7be1db61-acab-4c6b-8bea-b5330594fdcf"


@unittest.skipUnless(AVAILABLE, "optional CPU vision dependencies required")
class SparseLocalizationTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        rng = np.random.default_rng(88)
        self.xyz = rng.uniform([-12, -8, 10], [12, 8, 40], (240, 3))
        self.desc = rng.uniform(0, 1, (240, 128)).astype("<f4")
        self.desc /= np.linalg.norm(self.desc, axis=1, keepdims=True)
        self.profile = RouteViewProfile(GOAL, 960, 540, (0, 0, 1, 1), ((.99, .99, 1, 1),))
        self.route = SparseRoute(EPOCH, GOAL, "a"*64, pipeline_id(), self.profile,
            (450., 450., 480., 270.), tuple(tuple(map(float, row)) for row in self.xyz), self.desc.tobytes(),
            tuple((0., 0., float(z)) for z in range(0, 36, 5)), tuple(float(t) for t in range(8)),
            tuple(hashlib.sha256(str(t).encode()).hexdigest() for t in range(8)), (tuple(range(8)),)*240,
            "b"*64, tuple(range(8)))
        self.now, self.sequence = 10., 0
        self.localizer = self.tracker()
        self.center = np.array([2., .15, 6.])  # Two metres sideways in THIS synthetic scene.
        self.rotation = self.cv.Rodrigues(np.array([0., .25, 0.]))[0]
        self.localizer._features = lambda frame: self.features()

    def tracker(self, route=None):
        return RouteLocalizer(route or self.route, capture_epoch=EPOCH, episode_id=EPISODE,
                              goal_revision=GOAL, clock=lambda: self.now)

    def features(self, *, center=None, rotation=None):
        center = self.center if center is None else center
        rotation = self.rotation if rotation is None else rotation
        t = -rotation@center
        pixels = self.cv.projectPoints(self.xyz, self.cv.Rodrigues(rotation)[0], t,
                                      self.localizer.K, None)[0].reshape(-1, 2)
        mask = ((pixels[:, 0] >= 1) & (pixels[:, 0] < 959)
                & (pixels[:, 1] >= 1) & (pixels[:, 1] < 539))
        return pixels[mask], self.desc[mask]

    def observe(self, *, scene="active", **values):
        self.now += .2
        self.sequence += 1
        self.frame = PolicyFrame(EPOCH, self.sequence, self.now-.01, 960, 540, bytes(960*540*3))
        return self.localizer.observe(self.frame, episode_id=EPISODE, goal_revision=GOAL, scene=scene, **values)

    def test_translated_rotated_start_at_middle_uses_actual_pnp(self):
        for count in range(3):
            result = self.observe()
            self.assertEqual(result.state, "localized" if count == 2 else "confirming")
        self.np.testing.assert_allclose(result.center, self.center, atol=1e-5)
        self.np.testing.assert_allclose(self.np.reshape(result.rotation, (3, 3)), self.rotation, atol=1e-5)
        self.assertEqual(result.segment, 1)
        self.assertAlmostEqual(result.progress_units, 6., places=5)
        self.assertAlmostEqual(result.cross_track_units, (4+.15**2)**.5, places=5)
        self.assertGreater(result.inliers, 100)
        self.assertLess(result.median_error_px, .001)
        self.assertTrue(result.polyline_px)
        self.assertFalse(hasattr(result, "arrived"))

    def test_missing_landmarks_and_outliers_do_not_move_pose(self):
        pixels, desc = self.features()
        pixels = pixels.copy()
        pixels[:20] = self.np.random.default_rng(7).uniform([0, 0], [960, 540], (20, 2))
        solved = self.localizer._solve(pixels, desc)
        self.assertIsNotNone(solved)
        self.np.testing.assert_allclose(solved[0], self.center, atol=1e-5)
        self.assertLess(solved[2], len(desc))

    def test_alias_descriptors_are_not_arbitrarily_assigned_to_a_place(self):
        duplicate = self.desc.copy()
        duplicate[120:] = duplicate[:120]
        route = replace(self.route, descriptors=duplicate.tobytes())
        localizer = self.tracker(route)
        pixels, _ = self.features()
        # Every descriptor has an equally good alternative 3D landmark.
        self.assertIsNone(localizer._solve(pixels[:120], duplicate[:len(pixels[:120])]))

    def test_two_distant_covisible_aliases_require_disambiguation(self):
        duplicate = self.desc.copy()
        duplicate[120:] = duplicate[:120]
        xyz = self.xyz.copy()
        xyz[120:] = xyz[:120]+[25., 0., 0.]
        route = replace(self.route, points=tuple(tuple(map(float, row)) for row in xyz),
            descriptors=duplicate.tobytes(), landmark_views=((0, 1, 2),)*120+((5, 6, 7),)*120)
        tracker = self.tracker(route)
        pixels = self.cv.projectPoints(self.xyz[:120], self.cv.Rodrigues(self.rotation)[0],
            -self.rotation@self.center, tracker.K, None)[0].reshape(-1, 2)
        self.assertIsNone(tracker._solve(pixels, duplicate[:120]))

    def test_planar_geometry_and_insufficient_correspondences_are_unknown(self):
        xyz = self.xyz.copy()
        xyz[:, 1] = 0
        planar = self.tracker(replace(self.route, points=tuple(tuple(map(float, row)) for row in xyz)))
        pixels, desc = self.features()
        self.assertIsNone(planar._solve(pixels, desc))
        self.assertIsNone(self.localizer._solve(pixels[:15], desc[:15]))

    def test_crossing_trace_has_no_unique_progress(self):
        route = replace(self.route, camera_trace=((0., 0., 0.), (0., 0., 5.), (5., 0., 5.),
            (5., 0., 0.), (0., 0., 0.), (0., 0., -5.)), source_seconds=(0., 1., 2., 3., 4., 5.),
            reference_rgb_sha256=self.route.reference_rgb_sha256[:6], landmark_views=(tuple(range(6)),)*240,
            source_frame_indices=tuple(range(6)))
        self.assertIsNone(self.tracker(route)._nearest(self.np.zeros(3)))

    def test_gap_and_menu_require_reconfirmation(self):
        for _ in range(3):
            self.observe()
        self.assertEqual(self.observe(scene="menu").state, "unknown")
        self.assertEqual(self.observe().state, "confirming")
        self.observe()
        self.assertEqual(self.observe().state, "localized")
        self.now += 1
        self.assertEqual(self.observe().reason, "route_observation_gap")
        self.assertEqual(self.observe().state, "confirming")

    def test_pose_jump_is_rejected_without_forward_progress(self):
        for _ in range(3):
            self.observe()
        self.center = self.np.array([2., .15, 25.])
        self.assertEqual(self.observe().reason, "route_pose_discontinuity")

    def test_far_outside_corridor_does_not_yield_projected_guidance(self):
        self.localizer._solve = lambda *args: (self.np.array([30., 0., 0.]), self.np.eye(3), 30, 0.)
        result = self.observe()
        self.assertEqual(result.reason, "route_outside_observed_corridor")
        self.assertFalse(result.polyline_px)

    def test_epoch_episode_goal_and_repeated_sequence_retire_binding(self):
        for which in ("capture_epoch", "episode_id", "goal_revision", "sequence", "disconnected"):
            with self.subTest(which=which):
                tracker = self.tracker()
                frame = PolicyFrame(EPOCH, 1, self.now, 960, 540, bytes(960*540*3))
                kwargs = dict(episode_id=EPISODE, goal_revision=GOAL, scene="active")
                if which in kwargs:
                    kwargs[which] = EPOCH
                elif which == "capture_epoch":
                    frame = replace(frame, capture_epoch=GOAL)
                elif which == "sequence":
                    tracker.last_sequence = 1
                else:
                    kwargs["scene"] = "disconnected"
                self.assertEqual(tracker.observe(frame, **kwargs).reason, "route_binding_retired")
                self.assertTrue(tracker.retired)

    def test_geometry_age_and_expiry_during_calculation_stop_guidance(self):
        self.localizer._features = lambda frame: self.features()
        old_solve = self.localizer._solve

        def slow(*args):
            answer = old_solve(*args)
            self.now += .26
            return answer

        self.localizer._solve = slow
        self.assertEqual(self.observe().reason, "route_frame_expired_during_localization")
        for frame in (replace(self.frame, receiver_sequence=10, received_at=self.now-.3),
                      PolicyFrame(EPOCH, 11, self.now, 480, 270, bytes(480*270*3))):
            tracker = self.tracker()
            self.assertEqual(tracker.observe(frame, episode_id=EPISODE, goal_revision=GOAL,
                scene="active").reason, "route_scene_geometry_or_age_unqualified")

    def test_overlay_is_same_frame_copy_and_rejects_old_or_different_pixels(self):
        for _ in range(3):
            pose = self.observe()
        original = self.frame.rgb24
        drawn = render_guidance(self.frame, pose, clock=lambda: self.now)
        self.assertNotEqual(drawn, original)
        self.assertEqual(self.frame.rgb24, original)
        for frame, clock in ((self.frame, lambda: self.now+1),
                             (replace(self.frame, receiver_sequence=100), lambda: self.now),
                             (replace(self.frame, rgb24=b"x"*len(original)), lambda: self.now)):
            with self.assertRaisesRegex(ProtocolError, "route_overlay_not_bound"):
                render_guidance(frame, pose, clock=clock)

    def test_file_roundtrip_digest_schema_and_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"map.json"
            sha = self.route.save(path)
            self.assertEqual(SparseRoute.load(path, sha256=sha), self.route)
            with self.assertRaises(FileExistsError):
                self.route.save(path)
            with self.assertRaisesRegex(ProtocolError, "sparse_route_integrity"):
                SparseRoute.load(path, sha256="f"*64)
            data = json.loads(path.read_text())
            data["execution_qualified"] = True
            raw = json.dumps(data).encode()
            path.write_bytes(raw)
            with self.assertRaisesRegex(ProtocolError, "sparse_route_schema"):
                SparseRoute.load(path, sha256=hashlib.sha256(raw).hexdigest())

    def test_invalid_maps_cannot_silently_truncate_or_change_pipeline(self):
        for overrides in (dict(source_seconds=(0.,)*8), dict(points=((True, 0, 0),)*240),
                          dict(descriptors=bytes(len(self.route.descriptors))),
                          dict(camera_trace=(self.route.camera_trace[0],)*8),
                          dict(reference_rgb_sha256=("bad",)*8)):
            with self.subTest(overrides=list(overrides)):
                with self.assertRaises(ProtocolError):
                    replace(self.route, **overrides)
        with self.assertRaisesRegex(ProtocolError, "invalid_route_localizer_binding"):
            self.tracker(replace(self.route, pipeline_sha256="f"*64))

    def test_blank_real_rgb_has_no_pose(self):
        tracker = self.tracker()
        frame = PolicyFrame(EPOCH, 1, self.now, 960, 540, bytes(960*540*3))
        self.assertEqual(tracker.observe(frame, episode_id=EPISODE, goal_revision=GOAL,
                                        scene="active").reason, "route_pose_not_verified")

    def test_unobserved_route_sections_are_rejected_by_default(self):
        route = replace(self.route, landmark_views=((0, 1, 2),)*240)
        support = map_support(route)
        self.assertEqual(support["zero_landmark_views"], 5)
        self.assertEqual(support["neighborhoods_below_24"], 4)
        self.assertEqual(support["longest_unsupported_reference_span_seconds"], 3.)
        with self.assertRaisesRegex(ProtocolError, "route_map_has_unobserved_sections"):
            self.tracker(route)
        tracker = RouteLocalizer(route, capture_epoch=EPOCH, episode_id=EPISODE, goal_revision=GOAL,
                                 diagnostic_partial_map=True, clock=lambda: self.now)
        self.assertIsNotNone(tracker)
        self.assertFalse(support["navigation_qualified"])

    def test_builder_triangulates_known_views_and_rejects_bad_geometry(self):
        from scripts.pilot.route_landmark_builder import build, triangulate

        matrices, observations = [], []
        K = self.localizer.K
        for x in (-2., 0., 2.):
            center = self.np.array([x, 0., 0.])
            ext = self.np.column_stack([self.np.eye(3), -center])
            projected = self.xyz@K.T + (-center)@K.T
            pixels = projected[:, :2]/projected[:, 2:]
            matrices.append(ext)
            observations.append((pixels, self.desc))
        called = []
        landmarks, report = build(observations, matrices, K, checkpoint=lambda: called.append(True))
        self.assertEqual(report["accepted"], len(self.xyz))
        self.assertEqual(len(called), 1)
        self.np.testing.assert_allclose(landmarks[0][1], self.xyz[0], atol=1e-7)
        track = [(i, 0) for i in range(3)]
        pixels = [v[0].copy() for v in observations]
        pixels[1][0] += 50
        self.assertIsNone(triangulate(track, pixels, matrices, K))
        identical = [matrices[0]]*3
        self.assertIsNone(triangulate(track, [observations[0][0]]*3, identical, K))

    def test_probe_excludes_source_indices_even_when_rgb_conversion_changed(self):
        if importlib.util.find_spec("av") is None:
            self.skipTest("optional video dependency required")
        import av

        from scripts.pilot.check_route_localization import check

        manifest = b'{"fixture":true}'
        route = replace(self.route, source_capture_sha256=hashlib.sha256(manifest).hexdigest())
        capture = SimpleNamespace(geometry=(960, 540), originals={"manifest.json": manifest})

        def frames(_):
            for index in range(6):
                # Different RGB than all reference hashes, but the same source
                # indices. RGB conversion must not launder training frames.
                rgb = self.np.full((540, 960, 3), index, self.np.uint8)
                yield dict(index=index, relative_ticks_90k=index*9000), av.VideoFrame.from_ndarray(rgb, format="rgb24")

        with tempfile.TemporaryDirectory() as folder:
            with patch("scripts.pilot.check_route_localization.checkpoint"), \
                 patch("scripts.pilot.check_route_localization.validate_browser", return_value=capture), \
                 patch("scripts.pilot.check_route_localization.decoded_browser", frames):
                same = check("fixture", route, Path(folder)/"same")
                self.assertEqual(same["reference_indices_excluded"], 6)
                self.assertEqual(same["counts"], {})
                other = check("fixture", replace(route, source_capture_sha256="f"*64), Path(folder)/"other")
                self.assertEqual(other["reference_indices_excluded"], 0)
                self.assertEqual(other["counts"], {"unknown": 3})
