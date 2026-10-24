import importlib.util
import json
import tempfile
import unittest
import uuid
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from motor_worker.landmarks import RouteViewMatcher, RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError, VideoBinding
from motor_worker.route_memory import RouteProgress, TaughtRoute
from motor_worker.route_quality import analyze_quality
from motor_worker.teach import compile_capture, inspect_capture
from motor_worker.teach_capture import TeachCapture

AVAILABLE = all(importlib.util.find_spec(m) for m in ("cv2", "numpy", "av"))
EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
EPISODE = "f3867238-d651-4ce0-9e71-e892ce6e28fb"
GOAL = "7be1db61-acab-4c6b-8bea-b5330594fdcf"


@unittest.skipUnless(AVAILABLE, "optional vision and capture dependencies required")
class RouteMemoryTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.np = np
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.profile = RouteViewProfile(GOAL, 480, 270, (0, 0, 1, 1), ((0, 0, 1, .2),))
        matcher = RouteViewMatcher(self.profile, clock=lambda: 0)
        self.images = [np.random.default_rng(i).integers(0, 256, (270, 480, 3), np.uint8) for i in (17, 42, 77, 111)]
        self.views = tuple(matcher.learn(PolicyFrame(EPOCH, i+1, 0, 480, 270, rgb.tobytes()),
                                         keyframe_id=str(uuid.uuid4())) for i, rgb in enumerate(self.images))
        self.route = TaughtRoute(str(uuid.uuid4()), GOAL, EPISODE, "pedestrian", "a"*64,
                                self.profile, self.views, (0, 90000, 180000, 270000))
        self.now, self.seq = 1.0, 0
        self.progress = RouteProgress(self.route, capture_epoch=EPOCH, episode_id=EPISODE,
                                      goal_revision=GOAL, clock=lambda: self.now)

    def observe(self, image=0, **overrides):
        self.now += .2
        self.seq += 1
        frame = PolicyFrame(EPOCH, self.seq, self.now-.02, 480, 270, self.images[image].tobytes())
        return self.progress.observe(frame, **(dict(episode_id=EPISODE, goal_revision=GOAL, scene="active") | overrides))

    def test_adjacent_progress_requires_three_views_and_end_is_not_arrival(self):
        self.assertEqual(self.observe().state, "confirming")
        self.assertEqual(self.observe().state, "confirming")
        self.assertEqual(self.observe().checkpoint, 0)
        for image in (1, 2, 3):
            self.observe(image)
            self.observe(image)
            result = self.observe(image)
        self.assertEqual(result.state, "end_view")
        self.assertFalse(hasattr(result, "arrived"))

    def test_far_match_and_unknown_scene_do_not_authorize_route_progress(self):
        self.assertEqual(self.observe(3).state, "unknown")
        for _ in range(4):
            self.assertEqual(self.observe(scene="unknown").state, "unknown")
        self.assertIsNone(self.progress.index)

    def test_goal_episode_change_and_disconnect_retire_old_tracker(self):
        result = self.observe(episode_id=GOAL)
        self.assertEqual(result.reason, "route_episode_goal_or_capture_changed")
        self.assertEqual(self.observe().state, "unknown")

    def test_observation_gap_requires_new_confirmation_without_blind_progress(self):
        for _ in range(3):
            self.observe()
        self.now += 1
        self.assertEqual(self.observe().reason, "route_observation_gap")
        self.assertEqual(self.observe().state, "confirming")
        self.observe()
        self.assertEqual(self.observe().state, "tracking")

    def test_bundle_roundtrip_exact_hashes_and_untrusted_entry_paths(self):
        output = self.root/"route"
        self.route.save(output)
        restored = TaughtRoute.load(output)
        self.assertEqual(restored, self.route)
        self.assertFalse(json.loads((output/"route.json").read_text())["execution_qualified"])
        feature = output/(self.views[0].id+".json")
        feature.write_text(feature.read_text()+" ")
        with self.assertRaisesRegex(ProtocolError, "route_reference_integrity"):
            TaughtRoute.load(output)

    def test_shape_mode_pipeline_and_timestamp_order_are_pinned(self):
        for values in (dict(mode=[]), dict(source_ticks=(0, 0, 1, 2)),
                       dict(views=(self.views[0],)*4)):
            with self.assertRaises(ProtocolError):
                replace(self.route, **values)
        changed = replace(self.route, views=tuple(replace(v, pipeline_sha256="b"*64) for v in self.views))
        with self.assertRaisesRegex(ProtocolError, "route_pipeline_not_current"):
            RouteProgress(changed, capture_epoch=EPOCH, episode_id=EPISODE, goal_revision=GOAL, clock=lambda: 1)

    def capture(self, *, stationary=False):
        import av
        output = self.root/"capture"
        sink = TeachCapture(output, device_id=EPOCH, episode_id=EPISODE, profile_revision=GOAL, clock=lambda: 10)
        self.addCleanup(lambda: sink.finish(transport_success=False, input_released=False))
        sink.bind(VideoBinding(EPOCH, 480, 270))
        codec = av.CodecContext.create("libx264", "w")
        codec.width, codec.height, codec.pix_fmt = 480, 270, "yuv420p"
        codec.time_base = Fraction(1, 90000)
        codec.framerate = Fraction(10, 1)
        codec.options = {"preset": "ultrafast", "tune": "zerolatency", "crf": "18", "keyint": "10", "bf": "0"}
        count = 0
        for index in range(40):
            frame = av.VideoFrame.from_ndarray(self.images[0 if stationary else index//10], format="rgb24")
            frame.pts = index*9000
            frame.time_base = codec.time_base
            for packet in codec.encode(frame):
                self.assertTrue(sink.offer_access_unit(bytes(packet), packet.pts, 10+count/10), sink.failure)
                count += 1
        for packet in codec.encode(None):
            self.assertTrue(sink.offer_access_unit(bytes(packet), packet.pts, 10+count/10), sink.failure)
            count += 1
        self.assertTrue(sink.finish(transport_success=True, input_released=False)["complete"])
        return output

    def test_real_h264_capture_compiles_to_smaller_runtime_geometry(self):
        capture = self.capture()
        self.assertEqual(inspect_capture(capture)["frames"], 40)
        target = replace(self.profile, width=240, height=135)
        report = compile_capture(capture, self.root/"compiled", profile=target, world_revision=GOAL,
                                 mode="pedestrian", interval=.5)
        self.assertGreaterEqual(report["checkpoints"], 3)
        self.assertFalse(report["physical_execution_qualified"])
        bundle = TaughtRoute.load(self.root/"compiled")
        self.assertEqual(bundle.profile.width, 240)
        self.assertEqual(len(bundle.views), report["checkpoints"])

    def test_stationary_video_does_not_become_a_fake_route(self):
        capture = self.capture(stationary=True)
        with self.assertRaisesRegex(ProtocolError, "route_insufficient_distinct_views"):
            compile_capture(capture, self.root/"compiled", profile=self.profile,
                            world_revision=GOAL, mode="pedestrian")
        self.assertFalse((self.root/"compiled").exists())

    def test_quality_probe_excludes_reference_frames_and_does_not_promote_execution(self):
        capture = self.capture()
        compile_capture(capture, self.root/"compiled", profile=self.profile,
                        world_revision=GOAL, mode="pedestrian", interval=.5)
        route = TaughtRoute.load(self.root/"compiled")
        report = analyze_quality(capture, route, render_scale=.5, jpeg_quality=40)
        self.assertTrue(report["same_demonstration"])
        self.assertGreater(report["reference_frames_excluded"], 0)
        self.assertEqual(sum(report["counts"].values()), report["samples"])
        self.assertGreater(report["samples"], 0)
        for key in ("runtime_quality_qualified", "arrival_accepted", "scene_verified", "fleet_accepted"):
            self.assertFalse(report[key])
