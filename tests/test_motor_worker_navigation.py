import unittest
from dataclasses import replace

from motor_worker.navigation import NavigationObservation, NavigationSupervisor, background_motion
from motor_worker.protocol import ProtocolError

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"


class NavigationTests(unittest.TestCase):
    def observation(self, index, **kwargs):
        now = index * 0.25
        return NavigationObservation(
            EPOCH, index + 1, now - 0.02, now, "active", True, True, True, **kwargs
        )

    def stall(self, guard, start=1, **kwargs):
        for i in range(start, start + 13):
            directive = guard.observe(self.observation(i, **kwargs))
        return directive

    def test_distance_progress_keeps_following(self):
        guard = NavigationSupervisor()
        for i in range(1, 20):
            result = guard.observe(self.observation(i, distance_m=100 - i))
            self.assertEqual(result.action, "follow")

    def test_camera_motion_alone_does_not_fake_distance_progress(self):
        guard = NavigationSupervisor()
        result = self.stall(guard, distance_m=100, background_motion_px=20)
        self.assertEqual(result.action, "inspect_camera")
        waiting = guard.observe(self.observation(14, distance_m=100))
        self.assertEqual(waiting.action, "wait")
        self.assertEqual(waiting.operation_id, result.operation_id)

    def test_unknown_obstacle_is_not_blindly_jumped_or_walked_around(self):
        guard = NavigationSupervisor(jump_calibrated=True)
        result = self.stall(guard, distance_m=100)
        guard.complete_recovery(result.operation_id, confirmed=True, now=3.3)
        result = self.stall(guard, start=14, distance_m=100)
        self.assertEqual((result.action, result.reason), ("stop", "free_path_unknown"))

    def test_low_obstacle_jump_is_once_and_requires_calibration(self):
        guard = NavigationSupervisor(jump_calibrated=True)
        first = self.stall(guard, distance_m=100)
        guard.complete_recovery(first.operation_id, confirmed=True, now=3.3)
        second = self.stall(guard, start=14, distance_m=100, low_obstacle=True)
        self.assertEqual(second.action, "jump_double_tap")
        guard.complete_recovery(second.operation_id, confirmed=True, now=6.6)
        third = self.stall(guard, start=27, distance_m=100, low_obstacle=True)
        self.assertEqual(third.action, "stop")

    def test_detour_uses_assessed_free_side_and_has_finite_budget(self):
        guard = NavigationSupervisor(max_recoveries=2)
        first = self.stall(guard, distance_m=100)
        guard.complete_recovery(first.operation_id, confirmed=True, now=3.3)
        second = self.stall(guard, start=14, distance_m=100, free_side="left")
        self.assertEqual((second.action, second.side), ("detour", "left"))
        guard.complete_recovery(second.operation_id, confirmed=True, now=6.6)
        third = self.stall(guard, start=27, distance_m=100, free_side="right")
        self.assertEqual(third.reason, "recovery_budget_exhausted")

    def test_unknown_native_result_is_not_replayed(self):
        guard = NavigationSupervisor()
        first = self.stall(guard, distance_m=100)
        guard.complete_recovery(first.operation_id, confirmed=False, now=3.3)
        result = guard.observe(self.observation(14, distance_m=90))
        self.assertEqual((result.action, result.reason), ("stop", "recovery_receipt_unknown"))

    def test_target_loss_is_never_claimed_as_arrival(self):
        guard = NavigationSupervisor()
        result = guard.observe(replace(self.observation(1), target_visible=False))
        self.assertEqual((result.action, result.reason), ("stop", "target_missing_not_arrival"))

    def test_stale_control_and_scene_stop_before_motion(self):
        for change, expected in (
            ({"received_at": 0}, "receiver_frame_stale"),
            ({"control_ready": False}, "native_control_not_ready"),
            ({"scene": "disconnected"}, "game_disconnected"),
            ({"scene": "menu"}, "game_scene_not_active"),
        ):
            result = NavigationSupervisor().observe(replace(self.observation(2), **change))
            self.assertEqual((result.action, result.reason), ("stop", expected))

    def test_fall_waits_then_requires_confirmed_standing(self):
        guard = NavigationSupervisor()
        for i in range(1, 20):
            result = guard.observe(replace(self.observation(i), scene="fallen"))
            self.assertEqual(result.action, "wait")
        self.assertEqual(guard.observe(self.observation(20, distance_m=100)).action, "follow")
        for i in range(21, 47):
            result = guard.observe(replace(self.observation(i), scene="fallen"))
        self.assertEqual(result.reason, "fall_recovery_unconfirmed")

    def test_epoch_change_and_out_of_order_frames_cannot_continue(self):
        guard = NavigationSupervisor()
        guard.observe(self.observation(1))
        self.assertEqual(guard.observe(self.observation(1)).reason, "observation_order")
        guard = NavigationSupervisor()
        guard.observe(self.observation(1))
        different = replace(self.observation(2), epoch="0b59dcba-444f-4daa-9a22-aa1b1294ed98")
        self.assertEqual(guard.observe(different).reason, "capture_epoch_changed")

    def test_low_obstacle_does_not_authorize_uncalibrated_jump(self):
        guard = NavigationSupervisor(jump_calibrated=False)
        first = self.stall(guard, distance_m=100)
        guard.complete_recovery(first.operation_id, confirmed=True, now=3.3)
        result = self.stall(guard, start=14, distance_m=100, low_obstacle=True)
        self.assertEqual((result.action, result.reason), ("stop", "free_path_unknown"))

    def test_malformed_observations_are_refused_before_state_changes(self):
        for changes in (
            {"distance_m": True},
            {"scene": []},
            {"free_side": []},
            {"received_at": 1.0},
            {"background_motion_px": float("nan")},
        ):
            with self.assertRaises(ProtocolError):
                replace(self.observation(1), **changes)

    def test_fresh_frame_after_blind_gap_cannot_authorize_recovery(self):
        guard = NavigationSupervisor()
        guard.observe(self.observation(1, distance_m=100))
        result = guard.observe(self.observation(20, distance_m=100))
        self.assertEqual((result.action, result.reason), ("stop", "progress_observation_gap"))
        self.assertEqual(guard.recoveries, 0)
        self.assertEqual(guard.observe(self.observation(21, distance_m=100)).action, "follow")

    def test_recovery_does_not_survive_blind_gap_or_duplicate_capture_clock(self):
        guard = NavigationSupervisor()
        self.stall(guard, distance_m=100)
        result = guard.observe(self.observation(20, distance_m=100))
        self.assertEqual(result.reason, "recovery_observation_gap")
        guard = NavigationSupervisor()
        previous = self.observation(1)
        guard.observe(previous)
        result = guard.observe(replace(self.observation(2), received_at=previous.received_at))
        self.assertEqual(result.reason, "observation_clock_order")

    def test_one_animation_outlier_does_not_mask_three_seconds_of_no_world_motion(self):
        guard = NavigationSupervisor()
        for i in range(1, 14):
            result = guard.observe(self.observation(i, background_motion_px=12 if i == 7 else 0.1))
        self.assertEqual((result.action, result.reason), ("inspect_camera", "goal_progress_stalled"))

    def test_intermittent_real_motion_does_not_trigger_an_obstacle_manoeuvre(self):
        guard = NavigationSupervisor()
        for i in range(1, 14):
            result = guard.observe(self.observation(i, background_motion_px=2 if i % 2 else 0.1))
        self.assertEqual(result.action, "follow")


class BackgroundMotionTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("Optional motor vision extra is not installed")
        self.cv2, self.np = cv2, np
        rng = np.random.default_rng(17)
        self.frame = rng.integers(0, 256, (540, 960, 3), dtype=np.uint8)

    def test_translation_detected_and_moving_avatar_excluded(self):
        moved = self.cv2.warpAffine(self.frame, self.np.float32([[1, 0, 8], [0, 1, 0]]), (960, 540))
        self.assertAlmostEqual(background_motion(self.frame, moved), 8, delta=0.8)
        avatar = self.frame.copy()
        avatar[180:540, 350:620] = 0
        self.assertLess(background_motion(self.frame, avatar), 0.2)

    def test_textureless_frame_is_unknown_and_bad_geometry_is_refused(self):
        blank = self.np.zeros_like(self.frame)
        self.assertIsNone(background_motion(blank, blank))
        with self.assertRaises(ProtocolError):
            background_motion(blank[:100], blank[:100])

    def test_dim_background_features_survive_a_few_bright_corners(self):
        frame = self.frame // 6
        frame[180:195, 200:215] = 255
        moved = self.cv2.warpAffine(frame, self.np.float32([[1, 0, 5], [0, 1, 0]]), (960, 540))
        self.assertAlmostEqual(background_motion(frame, moved), 5, delta=0.8)

    def test_isolated_animated_patch_is_not_world_progress(self):
        frame = self.np.zeros_like(self.frame)
        frame[200:240, 210:250] = self.frame[200:240, 210:250]
        self.assertIsNone(background_motion(frame, frame))
