import importlib.util
import json
import unittest
from dataclasses import replace

from motor_worker.landmarks import RouteKeyframe, RouteViewMatcher, RouteViewProfile
from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError

AVAILABLE = all(importlib.util.find_spec(m) for m in ("cv2", "numpy"))
EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
OTHER = "0b59dcba-444f-4daa-9a22-aa1b1294ed98"
KEY = "ad767d4d-7cec-44bb-af3b-67b12bacbe01"
OTHER_KEY = "ad767d4d-7cec-44bb-af3b-67b12bacbe02"


@unittest.skipUnless(AVAILABLE, "optional motor vision dependencies required")
class RouteViewTests(unittest.TestCase):
    def setUp(self):
        import cv2
        import numpy as np

        self.cv, self.np = cv2, np
        self.profile = RouteViewProfile(EPOCH, 480, 270, (0, 0, 1, 1),
                                        ((0, 0, 1, 0.25), (0.4, 0.35, 0.6, 1)))
        self.matcher = RouteViewMatcher(self.profile, clock=lambda: 1.1)
        self.image = np.random.default_rng(17).integers(0, 256, (270, 480, 3), np.uint8)
        self.frame = self.frame_for(self.image)
        self.reference = self.matcher.learn(self.frame, keyframe_id=KEY)
        self.assertIsNotNone(self.reference)

    def frame_for(self, rgb):
        return PolicyFrame(EPOCH, 7, 1, 480, 270, rgb.tobytes())

    def test_brightness_translation_and_small_rotation_preserve_view_not_navigation(self):
        cv, np = self.cv, self.np
        images = [self.image, cv.convertScaleAbs(self.image, alpha=0.8, beta=10),
                  cv.warpAffine(self.image, np.float32([[1, 0, 5], [0, 1, 3]]), (480, 270)),
                  cv.warpAffine(self.image, cv.getRotationMatrix2D((240, 135), 3, 1), (480, 270))]
        for image in images:
            cue = self.matcher.compare(self.frame_for(image), (self.reference,))
            self.assertEqual(cue.status, "matched", cue)
            self.assertEqual(cue.keyframe_id, KEY)
            self.assertIn("not_pose_or_clearance", cue.reason)

    def test_different_scene_and_blank_image_do_not_match(self):
        for image in (self.np.zeros_like(self.image),
                      self.np.random.default_rng(42).integers(0, 256, self.image.shape, self.np.uint8)):
            cue = self.matcher.compare(self.frame_for(image), (self.reference,))
            self.assertEqual(cue.status, "unknown")
            self.assertIsNone(cue.keyframe_id)

    def test_same_view_at_two_candidate_locations_is_ambiguous(self):
        duplicate = replace(self.reference, id=OTHER_KEY)
        cue = self.matcher.compare(self.frame, (self.reference, duplicate))
        self.assertEqual(cue.reason, "ambiguous_route_views")
        self.assertIsNone(cue.keyframe_id)

    def test_hud_or_avatar_alone_cannot_be_taught_as_a_route_landmark(self):
        for rect in ((0, 0, 480, 67), (192, 95, 288, 270)):
            only_overlay = self.np.zeros_like(self.image)
            a, b, c, d = rect
            only_overlay[b:d, a:c] = self.image[b:d, a:c]
            self.assertIsNone(self.matcher.learn(self.frame_for(only_overlay), keyframe_id=KEY))

    def test_changed_profile_or_pipeline_does_not_reuse_reference(self):
        for ref in (replace(self.reference, profile_revision=OTHER),
                    replace(self.reference, pipeline_sha256="a" * 64)):
            self.assertEqual(self.matcher.compare(self.frame, (ref,)).reason, "reference_profile_mismatch")

    def test_fresh_new_capture_epoch_can_match_old_map_reference(self):
        fresh = replace(self.frame, capture_epoch=OTHER, receiver_sequence=100)
        result = self.matcher.compare(fresh, (self.reference,))
        self.assertEqual(result.status, "matched")
        self.assertEqual(result.capture_epoch, OTHER)
        self.assertEqual(result.receiver_sequence, 100)

    def test_stale_or_wrong_geometry_refuses_before_work(self):
        for frame in (replace(self.frame, received_at=0.8),
                      replace(self.frame, received_at=1.2),
                      PolicyFrame(EPOCH, 7, 1, 1, 1, b"\0" * 3)):
            self.assertIsNone(self.matcher.learn(frame, keyframe_id=KEY))
            self.assertEqual(self.matcher.compare(frame, (self.reference,)).reason, "stale_or_wrong_geometry")

    def test_expiration_during_cpu_work_is_not_promoted_to_current_position(self):
        now = [1.1]
        self.matcher.clock = lambda: now[0]
        original = self.matcher._features

        def delayed(frame):
            features = original(frame)
            now[0] = 1.3
            return features

        self.matcher._features = delayed
        self.assertEqual(self.matcher.compare(self.frame, (self.reference,)).reason,
                         "receiver_frame_expired_during_match")

    def test_reference_bytes_and_candidate_count_are_bounded(self):
        self.assertLessEqual(len(self.reference.descriptors), 1500*32)
        self.assertFalse(hasattr(self.reference, "rgb24"))
        for refs in ([], (), (self.reference,)*17, (self.reference, self.reference)):
            with self.assertRaises(ProtocolError):
                self.matcher.compare(self.frame, refs)
        with self.assertRaises(ProtocolError):
            replace(self.reference, descriptors=bytearray(self.reference.descriptors))
        with self.assertRaises(ProtocolError):
            replace(self.reference, descriptors=b"short")
        with self.assertRaises(ValueError):
            self.matcher.mask[0, 0] = 255

    def test_explicit_json_features_roundtrip_without_pixels_or_pickle(self):
        encoded = self.reference.encode()
        self.assertLess(len(encoded.encode()), 256*1024)
        restored = RouteKeyframe.parse(encoded)
        self.assertEqual(restored, self.reference)
        self.assertEqual(self.matcher.compare(self.frame, (restored,)).status, "matched")
        self.assertNotIn('"rgb24"', encoded)

    def test_untrusted_keyframe_schema_size_and_encoding_are_refused(self):
        data = json.loads(self.reference.encode())
        for changed in (data | {"command": "tap"}, data | {"source_sequence": True},
                        data | {"descriptors": "!not base64"}, data | {"points": [[0, 0, 0]]}):
            with self.assertRaises(ProtocolError):
                RouteKeyframe.parse(json.dumps(changed))
        with self.assertRaises(ProtocolError):
            RouteKeyframe.parse('{"id":"a","id":"b"}')
        with self.assertRaises(ProtocolError):
            RouteKeyframe.parse(" " * (256*1024+1))


class RouteViewSchemaTests(unittest.TestCase):
    def test_profile_roundtrip_and_unknown_fields_are_strict(self):
        profile = RouteViewProfile(EPOCH, 480, 270, (0, 0, 1, 1), ((0, 0, 1, 0.25),))
        self.assertEqual(RouteViewProfile.parse(profile.encode()), profile)
        with self.assertRaises(ProtocolError):
            RouteViewProfile.parse(json.dumps(json.loads(profile.encode()) | {"command": "tap"}))

    def test_invalid_roi_and_mutable_features_are_refused(self):
        with self.assertRaises(ProtocolError):
            RouteViewProfile(EPOCH, 480, 270, (0, 0, 2, 1), ((0, 0, 0.1, 1),))
        with self.assertRaises(ProtocolError):
            RouteKeyframe(KEY, EPOCH, "a"*64, "b"*64, EPOCH, 1, [], b"")
