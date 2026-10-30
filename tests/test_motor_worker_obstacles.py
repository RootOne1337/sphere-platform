import hashlib
import unittest
from dataclasses import replace

from motor_worker.obstacles import (
    ObjectBox,
    ObjectObservation,
    ObstacleProfile,
    inspect_obstacles,
)
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
OTHER = "0b59dcba-444f-4daa-9a22-aa1b1294ed98"
MODEL = "a" * 64
PIPELINE_FP32 = "c" * 64


class ObstacleInspectionTests(unittest.TestCase):
    def setUp(self):
        self.frame = PolicyFrame(EPOCH, 7, 1, 1, 1, b"\0\0\0")
        self.profile = ObstacleProfile(EPOCH, MODEL, PIPELINE_FP32, (0.35, 0.35, 0.65, 0.75), frozenset({"fence", "wall"}))
        self.fence = ObjectBox("fence", 0.8, (0.1, 0.3, 0.9, 0.6))
        self.observation = ObjectObservation(
            EPOCH, 7, 1, 1.08, EPOCH, MODEL, PIPELINE_FP32, hashlib.sha256(self.frame.rgb24).hexdigest(),
            1, 1, (self.fence,),
        )

    def inspect(self, *, observation=None, frame=None, profile=None, now=1.1, scene_active=True):
        return inspect_obstacles(
            observation or self.observation, frame or self.frame, profile or self.profile,
            now=now, scene_active=scene_active,
        )

    def test_fence_intersecting_corridor_produces_only_a_stop_inspection_cue(self):
        cue = self.inspect()
        self.assertEqual(cue.status, "suspected_obstacle")
        self.assertEqual(cue.candidates, (self.fence,))
        self.assertIn("not_depth", cue.reason)
        self.assertFalse(hasattr(cue, "free_side"))

    def test_model_silence_never_authorizes_movement(self):
        for objects in ((), (replace(self.fence, confidence=0.1),),
                        (replace(self.fence, label="person"),),
                        (replace(self.fence, xyxy=(0, 0, 0.1, 0.1)),)):
            cue = self.inspect(observation=replace(self.observation, objects=objects))
            self.assertEqual(cue.status, "unknown")
            self.assertEqual(cue.candidates, ())

    def test_delayed_consumer_and_slow_inference_both_expire(self):
        self.assertEqual(self.inspect(now=1.251).reason, "receiver_frame_stale")
        slow = replace(self.observation, completed_at=1.251)
        self.assertEqual(self.inspect(observation=slow, now=1.251).status, "unknown")
        self.assertEqual(self.inspect(now=1.07).status, "unknown")

    def test_reused_sequence_with_different_pixels_or_dimensions_is_rejected(self):
        for frame in (replace(self.frame, rgb24=b"\xff\0\0"),
                      PolicyFrame(EPOCH, 7, 1, 2, 1, b"\0" * 6)):
            self.assertEqual(self.inspect(frame=frame).reason, "frame_mismatch")

    def test_epoch_profile_model_and_clock_changes_invalidate_cue(self):
        for observation, reason in (
            (replace(self.observation, capture_epoch=OTHER), "frame_mismatch"),
            (replace(self.observation, receiver_sequence=8), "frame_mismatch"),
            (replace(self.observation, received_at=0.99), "frame_mismatch"),
            (replace(self.observation, profile_revision=OTHER), "profile_mismatch"),
            (replace(self.observation, model_sha256="b" * 64), "profile_mismatch"),
        ):
            self.assertEqual(self.inspect(observation=observation).reason, reason)

    def test_launcher_objects_do_not_become_game_geometry(self):
        self.assertEqual(self.inspect(scene_active=False).reason, "gameplay_unconfirmed")

    def test_fast_fp16_cannot_borrow_same_checkpoint_fp32_qualification(self):
        fp16 = replace(self.observation, pipeline_sha256="d" * 64)
        self.assertEqual(fp16.model_sha256, self.profile.model_sha256)
        self.assertEqual(self.inspect(observation=fp16).reason, "profile_mismatch")

    def test_roi_overlap_is_area_fraction_not_intersection_over_whole_large_object(self):
        # A large wall covering the small approach corridor must still be caught.
        wall = ObjectBox("wall", 0.9, (0, 0, 1, 1))
        cue = self.inspect(observation=replace(self.observation, objects=(wall,)))
        self.assertEqual(cue.candidates, (wall,))
        edge = replace(wall, xyxy=(0, 0, 0.351, 1))
        self.assertEqual(self.inspect(observation=replace(self.observation, objects=(edge,))).status, "unknown")

    def test_nonfinite_out_of_bounds_and_degenerate_boxes_are_refused(self):
        for xyxy in ((0, 0, 0, 1), (0, 0, 1.1, 1), (0, 0, float("nan"), 1),
                     (True, 0, 1, 1), [0, 0, 1, 1]):
            with self.assertRaises(ProtocolError):
                replace(self.fence, xyxy=xyxy)
        for value in (True, float("inf"), -0.1, 1.1):
            with self.assertRaises(ProtocolError):
                replace(self.fence, confidence=value)

    def test_unbounded_or_mutable_result_is_refused(self):
        for objects in ([self.fence], (self.fence,) * 101, (None,)):
            with self.assertRaises(ProtocolError):
                replace(self.observation, objects=objects)
        with self.assertRaises(ProtocolError):
            replace(self.observation, rgb_sha256="missing")
        with self.assertRaises(ProtocolError):
            self.inspect(scene_active="yes")
