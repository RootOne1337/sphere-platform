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
    inlier_spatial_support,
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
        # Feature extraction is mocked in these state tests; distinct source
        # images must still represent distinct observations.
        rgb = self.sequence.to_bytes(4, "little") + bytes(960*540*3 - 4)
        self.frame = PolicyFrame(EPOCH, self.sequence, self.now-.01, 960, 540, rgb)
        return self.localizer.observe(self.frame, episode_id=EPISODE, goal_revision=GOAL, scene=scene, **values)

    def test_repeated_rgb_cannot_confirm_and_requires_new_observations(self):
        self.assertEqual(self.observe().state, "confirming")
        original = self.frame
        for seq in range(2, 5):
            self.now += .2
            duplicate = replace(original, receiver_sequence=seq, received_at=self.now-.01)
            pose = self.localizer.observe(duplicate, episode_id=EPISODE, goal_revision=GOAL, scene="active")
            self.assertEqual((pose.state, pose.reason), ("unknown", "route_repeated_rgb_not_independent"))
        self.sequence = 4
        self.assertEqual(self.observe().state, "confirming")
        self.assertEqual(self.observe().state, "confirming")
        self.assertEqual(self.observe().state, "localized")

    def test_repeat_after_confirmed_pose_revokes_pose(self):
        for _ in range(3):
            pose = self.observe()
        self.assertEqual(pose.state, "localized")
        self.now += .2
        duplicate = replace(self.frame, receiver_sequence=4, received_at=self.now-.01)
        pose = self.localizer.observe(duplicate, episode_id=EPISODE, goal_revision=GOAL, scene="active")
        self.assertEqual((pose.state, pose.reason), ("unknown", "route_repeated_rgb_not_independent"))
        self.assertEqual(self.localizer.confirmations, 0)

    def test_alternating_two_images_cannot_fake_three_confirmations(self):
        self.assertEqual(self.observe().state, "confirming")
        first = self.frame
        self.assertEqual(self.observe().state, "confirming")
        self.now += .2
        alternating = replace(first, receiver_sequence=3, received_at=self.now-.01)
        result = self.localizer.observe(alternating, episode_id=EPISODE, goal_revision=GOAL, scene="active")
        self.assertEqual((result.state, result.reason), ("unknown", "route_repeated_rgb_not_independent"))
        self.assertEqual(self.localizer.confirmations, 0)

    def test_competing_pose_rejects_different_heading_at_same_center(self):
        center = self.np.zeros(3)
        identity = self.np.eye(3)
        opposite = self.cv.Rodrigues(self.np.array([0., self.np.pi, 0.]))[0]
        small_turn = self.cv.Rodrigues(self.np.array([0., .2, 0.]))[0]
        best = (center, identity, 100, .5)
        self.assertTrue(self.localizer._competing_pose(best, (center, opposite, 75, .5)))
        self.assertFalse(self.localizer._competing_pose(best, (center, opposite, 74, .5)))
        self.assertFalse(self.localizer._competing_pose(best, (center, small_turn, 90, .5)))
        self.assertTrue(self.localizer._competing_pose(best, (self.np.array([100., 0., 0.]), identity, 90, .5)))

    def test_fresh_confirmed_pose_disambiguates_verified_distant_facade_alias(self):
        np=self.np;identity=np.eye(3);near=(np.array([0.,0.,6.2]),identity,80,.5)
        far=(np.array([100.,0.,6.2]),identity,100,.4)
        self.assertIsNone(self.localizer._rank_proposals([far,near]))
        self.localizer.previous=(np.array([0.,0.,6.]),identity,6.,10.)
        self.localizer.confirmations=3;self.localizer.last_received=10.2
        self.assertIs(self.localizer._rank_proposals([far,near]),near)
        self.localizer.last_received=11.
        self.assertIsNone(self.localizer._rank_proposals([far,near]))

    def test_recent_neighborhood_is_only_a_candidate_after_fresh_confirmation(self):
        self.assertIsNone(self.localizer._recent_reference_candidate())
        self.localizer.previous=(self.np.array([0.,0.,6.]),self.np.eye(3),6.,10.)
        self.localizer.last_received=10.2;self.localizer.confirmations=2
        self.assertIsNone(self.localizer._recent_reference_candidate())
        self.localizer.confirmations=3
        self.assertIsNotNone(self.localizer._recent_reference_candidate())
        # A remembered location is never a solution without current evidence.
        self.assertIsNone(self.localizer._solve(self.np.empty((0,2)),self.np.empty((0,128))))
        self.localizer.last_received=10.501
        self.assertIsNone(self.localizer._recent_reference_candidate())

    def test_nearby_stationary_reference_views_are_not_a_distant_return_route(self):
        np=self.np
        self.localizer.trace=np.array([[0.,0.,z] for z in [0,.01,0,.01,5,10,15,20]])
        self.localizer.lengths=np.linalg.norm(np.diff(self.localizer.trace,axis=0),axis=1)
        self.localizer.cumulative=np.r_[0,np.cumsum(self.localizer.lengths)]
        self.assertIsNotNone(self.localizer._nearest(np.array([0.,0.,.005])))
        self.localizer.trace=np.array([[0.,0.,z] for z in [0,5,10,15,20,25,0,5]])
        self.localizer.lengths=np.linalg.norm(np.diff(self.localizer.trace,axis=0),axis=1)
        self.localizer.cumulative=np.r_[0,np.cumsum(self.localizer.lengths)]
        self.assertIsNone(self.localizer._nearest(np.array([0.,0.,.005])))

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

    def test_horizontal_only_inliers_are_not_accepted_as_camera_pose(self):
        np=self.np
        rng=np.random.default_rng(113)
        def pose_points(low_y,high_y):
            xy=np.column_stack((rng.uniform(10,950,120),rng.uniform(low_y,high_y,120)))
            z=rng.uniform(8,40,len(xy))
            xyz=np.column_stack(((xy[:,0]-480)*z/450,(xy[:,1]-270)*z/450,z))
            return xyz,xy
        one_strip,strip_xy=pose_points(365,385)
        self.assertGreaterEqual(len({int(x//240) for x in strip_xy[:,0]}),4)
        self.assertFalse(inlier_spatial_support(strip_xy))
        self.assertIsNone(self.localizer._verify_correspondences(one_strip,strip_xy))
        spread,spread_xy=pose_points(20,520)
        self.assertTrue(inlier_spatial_support(spread_xy))
        self.assertIsNotNone(self.localizer._verify_correspondences(spread,spread_xy))

    def test_grid_boundary_does_not_make_a_narrow_band_observable(self):
        xy=self.np.array([(x,y) for x in (40,280,520,760) for y in (179.,181.) for _ in range(3)])
        self.assertFalse(inlier_spatial_support(xy))
        xy[0]=[-1,180]
        self.assertFalse(inlier_spatial_support(xy))

    def test_one_outlier_cannot_make_a_narrow_cloud_observable(self):
        rng=self.np.random.default_rng(114)
        xy=self.np.column_stack((rng.uniform(5,955,100),rng.uniform(365,385,100)))
        xy[0,1]=50.
        self.assertFalse(inlier_spatial_support(xy))

    def test_spatial_support_is_stable_across_arbitrary_grid_boundaries(self):
        xy=self.np.array([(x,y) for x in self.np.linspace(60,900,12) for y in self.np.linspace(200,345,8)])
        for dy in (-75.,0.,75.):
            with self.subTest(vertical_shift=dy):
                self.assertTrue(inlier_spatial_support(xy+[0,dy]))

    def test_diagonal_line_and_local_cluster_with_remote_outliers_are_rejected(self):
        x=self.np.linspace(30,930,100)
        line=self.np.column_stack((x,30+x*.5))
        self.assertFalse(inlier_spatial_support(line))
        rng=self.np.random.default_rng(115)
        cluster=rng.uniform([450,250],[460,260],(100,2))
        outliers=self.np.array([[5,5],[950,5],[5,530],[950,530]])
        self.assertFalse(inlier_spatial_support(self.np.vstack((cluster,outliers))))

    def test_candidate_limit_is_bounded_and_controls_search_without_changing_pnp_checks(self):
        views = 32
        route = replace(self.route,
            camera_trace=tuple((0., 0., float(z)) for z in range(views)),
            source_seconds=tuple(float(z) for z in range(views)),
            reference_rgb_sha256=tuple(hashlib.sha256(str(z).encode()).hexdigest() for z in range(views)),
            landmark_views=tuple((4*(i//30), 4*(i//30)+1, 4*(i//30)+2) for i in range(240)),
            source_frame_indices=tuple(range(views)))
        matches = [[SimpleNamespace(trainIdx=i, distance=.1)] for i in range(240)]
        matcher = SimpleNamespace(knnMatch=lambda *args, **kwargs: matches)
        for limit in (3, 5, 8):
            tracker = RouteLocalizer(route, capture_epoch=EPOCH, episode_id=EPISODE,
                                     goal_revision=GOAL, candidate_limit=limit)
            visited = []
            tracker._solve_subset = lambda pixels, desc, indices: visited.append(indices) or None
            with patch.object(self.cv, 'BFMatcher', return_value=matcher):
                self.assertIsNone(tracker._solve(self.np.zeros((240, 2)), self.desc))
            self.assertEqual(len(visited), limit)
        for bad in (True, 2, 9):
            with self.assertRaisesRegex(ProtocolError, 'invalid_route_localizer_binding'):
                RouteLocalizer(route, capture_epoch=EPOCH, episode_id=EPISODE, goal_revision=GOAL,
                               candidate_limit=bad)

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

    def test_recorded_pauses_keep_timestamps_without_dividing_by_zero(self):
        trace=((0.,0.,0.),(0.,0.,0.),(0.,0.,5.),(0.,0.,10.),
               (0.,0.,10.),(0.,0.,15.),(0.,0.,20.),(0.,0.,20.))
        route=replace(self.route,camera_trace=trace)
        tracker=self.tracker(route)
        with self.np.errstate(divide='raise',invalid='raise'):
            for z in (0.,7.,10.,16.,20.):
                segment,progress,distance=tracker._nearest(self.np.array([0.,0.,z]))
                self.assertAlmostEqual(progress,z)
                self.assertAlmostEqual(distance,0.)
                self.assertGreater(tracker.lengths[segment],0.)
        self.assertEqual(route.source_seconds,self.route.source_seconds)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'paused.json';sha=route.save(path)
            self.assertEqual(SparseRoute.load(path,sha256=sha),route)

    def test_long_dwell_does_not_collapse_the_motion_scale(self):
        from motor_worker.route_localization import trace_step_scale
        self.assertEqual(trace_step_scale([0.,0.,0.,0.,5.,5.]),5.)
        with self.assertRaises(ProtocolError):trace_step_scale([0.,0.])
        for invalid in ([float('nan')],[float('inf')],[-1.,5.]):
            with self.assertRaises(ProtocolError):trace_step_scale(invalid)

    def test_batched_votes_preserve_exact_alias_weights_and_candidate_order(self):
        from motor_worker.route_localization import coarse_reference_votes
        from types import SimpleNamespace
        rng=self.np.random.default_rng(29)
        visibility=rng.integers(0,2,(174,4096),dtype=self.np.uint8)
        coarse=[]
        for _ in range(2048):
            distances=sorted(rng.uniform(.1,.9,4))
            coarse.append(tuple(SimpleNamespace(trainIdx=int(rng.integers(4096)),distance=d) for d in distances))
        coarse.append(())
        old=self.np.zeros(174)
        for pairs in coarse:
            if not pairs:continue
            plausible=[m for m in pairs if m.distance<.7 and m.distance<=pairs[0].distance*1.2+1e-5]
            for match in plausible:old+=visibility[:,match.trainIdx]*(1-match.distance)/len(plausible)
        new=coarse_reference_votes(coarse,visibility)
        self.np.testing.assert_allclose(new,old,atol=1e-9,rtol=1e-12)
        self.np.testing.assert_array_equal(self.np.argsort(new),self.np.argsort(old))
        self.np.testing.assert_array_equal(coarse_reference_votes([()],visibility),self.np.zeros(174))

    def test_large_map_builds_one_coarse_index_but_keeps_the_exact_pnp_gate(self):
        from types import SimpleNamespace
        tracker=self.tracker()
        tracker.descriptors=self.np.tile(tracker.descriptors,(4,1))
        matcher=SimpleNamespace(add=unittest.mock.Mock(),train=unittest.mock.Mock(),
            knnMatch=unittest.mock.Mock(return_value=[]))
        with patch.object(self.cv,'FlannBasedMatcher',return_value=matcher) as create:
            self.assertEqual(tracker._coarse_matches(self.desc),[])
            self.assertEqual(tracker._coarse_matches(self.desc),[])
        create.assert_called_once_with(dict(algorithm=1,trees=4),dict(checks=64))
        matcher.train.assert_called_once();matcher.add.assert_called_once()
        self.assertEqual(matcher.knnMatch.call_count,2)
        self.assertIsNone(tracker._verify_correspondences(self.xyz[:10],self.np.zeros((10,2))))

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

    def test_missing_reference_interval_rejects_route_and_never_draws_across_gap(self):
        route = replace(self.route, source_seconds=(0., 1., 2., 4., 5., 6., 7., 8.))
        support = map_support(route)
        self.assertTrue(support["all_reference_neighborhoods_supported"])
        self.assertFalse(support["all_reference_intervals_observed"])
        self.assertEqual(support["unobserved_intervals"], [{"start_seconds": 2., "end_seconds": 4.}])
        with self.assertRaisesRegex(ProtocolError, "route_map_has_unobserved_sections"):
            self.tracker(route)
        tracker = RouteLocalizer(route, capture_epoch=EPOCH, episode_id=EPISODE, goal_revision=GOAL,
                                 diagnostic_partial_map=True, clock=lambda: self.now)
        self.assertIsNone(tracker._nearest(self.np.array([0., 0., 12.5])))
        points = tracker._project(self.np.zeros(3), self.np.eye(3), 1)
        self.assertEqual(len(points), 1)

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
                self.assertEqual(other["candidate_limit"], 3)
                self.assertEqual(other["compute_freshness_lower_bound"]["scope"], "compute_only_lower_bound")

    def test_offline_compute_budget_is_lower_bound_not_a_freshness_claim(self):
        from scripts.pilot.check_route_localization import compute_freshness_lower_bound

        samples = [
            {"compute_ms": 250., "pose": {"state": "localized"}},
            {"compute_ms": 251., "pose": {"state": "localized"}},
            {"compute_ms": 280., "pose": {"state": "unknown"}},
        ]
        result = compute_freshness_lower_bound(samples)
        self.assertEqual(result["receiver_age_budget_ms"], 250)
        self.assertEqual(result["samples_exceeding_budget"], 2)
        self.assertEqual(result["localized_samples_exceeding_budget"], 1)
        self.assertEqual(result["scope"], "compute_only_lower_bound")

    def test_offline_probe_rejects_invalid_candidate_limit(self):
        from scripts.pilot.check_route_localization import check

        with tempfile.TemporaryDirectory() as folder:
            for bad in (True, 2, 9):
                with self.subTest(value=bad), self.assertRaisesRegex(ProtocolError, 'invalid_localization_probe'):
                    check('fixture', self.route, Path(folder)/'out', candidate_limit=bad)
