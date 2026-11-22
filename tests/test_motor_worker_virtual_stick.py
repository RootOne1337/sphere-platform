import math
import unittest

from motor_worker.policy import ActionChunk, GamepadState, KeyboardMouseState
from motor_worker.protocol import ProtocolError
from motor_worker.virtual_stick import (
    GamepadStickTrajectory,
    StickGeometry,
    VirtualStickContact,
    WasdStickContact,
)


class VirtualStickTests(unittest.TestCase):
    def setUp(self):
        self.stick = VirtualStickContact(StickGeometry(960, 540, 140, 430, 60))

    def test_move_neutral_move_is_one_continuous_contact_not_double_tap(self):
        s, events, held = self.stick, [], False
        for i, (x, y) in enumerate(((0, -1), (0, 0), (1, 0), (0, 0), (0, -1))):
            t = 1 + i * 0.2
            s.observe(x, y, t - 0.15, t)
            for at in (t, t + 0.02):
                event = s.next_event(at, at - 0.01, held=held)
                if event:
                    events.append(event)
                    s.sent(event, at)
                    held = event.action != 1
        self.assertEqual([v.action for v in events], [0, 2, 2, 2, 2, 2])
        self.assertEqual(sum(v.action == 0 for v in events), 1)
        self.assertFalse(any(v.action == 1 for v in events))
        self.assertIn((140, 430), [(v.x, v.y) for v in events[1:]])

    def test_slow_but_fresh_250ms_inference_does_not_release_between_results(self):
        s = self.stick
        s.observe(0, -1, 1, 1.25)
        down = s.next_event(1.25, 1.24, held=False)
        s.sent(down, 1.25)
        move = s.next_event(1.27, 1.26, held=True)
        s.sent(move, 1.27)
        self.assertIsNone(s.next_event(1.49, 1.48, held=True))
        s.observe(0, -1, 1.25, 1.5)
        self.assertIsNone(s.next_event(1.51, 1.5, held=True))

    def test_expiry_releases_and_reengagement_cannot_be_a_rapid_double_tap(self):
        s = self.stick
        s.observe(0, -1, 1, 1.1)
        s.sent(s.next_event(1.1, 1.09, held=False), 1.1)
        up = s.next_event(1.46, 1.45, held=True)
        self.assertEqual(up.action, 1)
        s.sent(up, 1.46)
        s.observe(0, -1, 1.5, 1.6)
        self.assertIsNone(s.next_event(1.6, 1.59, held=False))
        s.observe(0, -1, 2.1, 2.2)
        self.assertEqual(s.next_event(2.2, 2.19, held=False).action, 0)

    def test_lost_video_releases_even_with_a_recent_prediction(self):
        s = self.stick
        s.observe(1, 0, 1, 1.1)
        self.assertEqual(s.next_event(1.2, 0.9, held=True).action, 1)
        self.assertIsNone(s.next_event(1.2, 0.9, held=True, pending=True))

    def test_stale_result_does_not_extend_a_contact(self):
        self.assertFalse(self.stick.observe(0, -1, 1, 1.41))
        self.assertIsNone(self.stick.next_event(1.42, 1.41, held=False))

    def test_invalid_axes_clock_and_geometry_fail_without_coercion(self):
        for x in (True, math.nan, math.inf, 2):
            with self.assertRaises(ProtocolError):
                self.stick.observe(x, 0, 1, 1.1)
        with self.assertRaises(ProtocolError):
            self.stick.observe(0, 0, 2, 1)
        with self.assertRaises(ProtocolError):
            StickGeometry(960, 540, 20, 430, 60)


class GamepadTrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.stick = GamepadStickTrajectory(StickGeometry(960, 540, 140, 430, 60))

    def chunk(self, axes, hz=60):
        return ActionChunk(
            tuple(
                GamepadState(tuple(axis), (0, 0), GamepadState.neutral().buttons) for axis in axes
            ),
            hz,
        )

    def test_later_states_execute_with_one_contact_and_correct_y_axis(self):
        s = self.stick
        s.observe(self.chunk([(0, 1)] * 6 + [(1, 0)] * 6 + [(0, 0)] * 6), 1, 1.1)
        events = []
        for now, held in ((1.1, False), (1.12, True), (1.22, True), (1.32, True)):
            event = s.next_event(now, now, held=held)
            events.append(event)
            s.sent(event, now)
        self.assertEqual([event.action for event in events], [0, 2, 2, 2])
        self.assertEqual(
            [(event.x, event.y) for event in events],
            [(140, 430), (140, 370), (200, 430), (140, 430)],
        )

    def test_repeated_forward_chunks_hold_direction_without_micro_taps(self):
        s, events, held = self.stick, [], False
        for plan in range(5):
            started = 1 + plan * 0.2
            s.observe(self.chunk([(0, 1)] * 18), started - 0.1, started)
            for tick in range(10):
                now = started + tick * 0.02
                event = s.next_event(now, now, held=held)
                if event:
                    events.append(event)
                    s.sent(event, now)
                    held = event.action != 1
        self.assertEqual([event.action for event in events], [0, 2])
        self.assertEqual((events[-1].x, events[-1].y), (140, 370))

    def test_new_prediction_atomically_replaces_remaining_old_plan(self):
        s = self.stick
        s.observe(self.chunk([(0, 1)] * 18), 1, 1.1)
        s.sent(s.next_event(1.1, 1.1, held=False), 1.1)
        s.observe(self.chunk([(-1, 0)] * 18), 1.15, 1.25)
        event = s.next_event(1.26, 1.26, held=True)
        self.assertEqual((event.action, event.x, event.y), (2, 80, 430))
        self.assertGreater(s.superseded_states, 0)

    def test_pending_ack_does_not_queue_and_late_tick_skips_history(self):
        s = self.stick
        s.observe(self.chunk([(1, 0)] * 6 + [(-1, 0)] * 12), 1, 1.1)
        self.assertIsNone(s.next_event(1.12, 1.12, held=True, pending=True))
        event = s.next_event(1.25, 1.25, held=True)
        self.assertEqual(event.x, 80)
        self.assertGreater(s.skipped_states, 0)
        s.sent(event, 1.25)
        self.assertIsNone(s.next_event(1.25, 1.25, held=True))

    def test_finite_horizon_does_not_hold_last_direction_indefinitely(self):
        s = self.stick
        s.observe(self.chunk([(0, 1)] * 18), 1, 1.1)
        self.assertEqual(s.next_event(1.401, 1.401, held=True).action, 1)

    def test_stale_result_invalidates_old_plan_and_rollback_is_rejected(self):
        s = self.stick
        s.observe(self.chunk([(0, 1)] * 18), 1, 1.1)
        self.assertFalse(s.observe(self.chunk([(0, 1)] * 18), 1.2, 1.61))
        self.assertEqual(s.next_event(1.62, 1.62, held=True).action, 1)
        with self.assertRaises(ProtocolError):
            s.observe(self.chunk([(0, 1)] * 18), 1.3, 1.6)

    def test_keyboard_chunk_long_horizon_and_clock_rollback_rejected(self):
        for chunk in (
            ActionChunk((KeyboardMouseState.neutral(),), 20),
            self.chunk([(0, 1)] * 18, 20),
        ):
            with self.assertRaises(ProtocolError):
                self.stick.observe(chunk, 1, 1.1)
        self.stick.observe(self.chunk([(0, 1)] * 18), 1, 1.1)
        self.stick.next_event(1.2, 1.2, held=False)
        with self.assertRaises(ProtocolError):
            self.stick.next_event(1.19, 1.19, held=True)


class WasdContactTests(unittest.TestCase):
    def state(self, keys=(), **kwargs):
        return KeyboardMouseState(keys, kwargs.get("buttons", ()), kwargs.get("x", 0), 0)

    def test_5hz_same_key_neutral_and_direction_change_share_one_contact(self):
        stick = WasdStickContact(StickGeometry(960, 540, 140, 430, 60))
        events, held = [], False
        for index, keys in enumerate((("w",), ("w",), (), ("d",), ("d",))):
            now = 1 + index * 0.2
            stick.observe(self.state(keys), now - 0.1, now)
            for tick in (now, now + 0.02):
                event = stick.next_event(tick, tick, held=held)
                if event:
                    events.append(event)
                    stick.sent(event, tick)
                    held = event.action != 1
        self.assertEqual([e.action for e in events], [0, 2, 2, 2])
        self.assertEqual(
            [(e.x, e.y) for e in events], [(140, 430), (140, 370), (140, 430), (200, 430)]
        )

    def test_diagonal_saturates_circle_and_opposite_keys_cancel(self):
        stick = WasdStickContact(StickGeometry(960, 540, 140, 430, 60))
        stick.observe(self.state(("w", "d")), 1, 1.1)
        self.assertEqual(stick.contact.target, (182, 388))
        stick.observe(self.state(("w", "s", "a", "d")), 1.2, 1.3)
        self.assertEqual(stick.contact.target, (140, 430))

    def test_other_channels_require_explicit_mask_and_are_counted(self):
        geometry = StickGeometry(960, 540, 140, 430, 60)
        state = self.state(("w", "Space"), buttons=("0",), x=5)
        strict = WasdStickContact(geometry)
        with self.assertRaises(ProtocolError):
            strict.observe(state, 1, 1.1)
        self.assertIsNone(strict.contact.last_result)
        masked = WasdStickContact(geometry, mask_other_channels=True)
        self.assertTrue(masked.observe(state, 1, 1.1))
        self.assertEqual(masked.masked_predictions, 1)
        self.assertEqual(masked.contact.target, (140, 370))

    def test_stale_frame_and_pending_ack_never_replay_held_w(self):
        stick = WasdStickContact(StickGeometry(960, 540, 140, 430, 60))
        stick.observe(self.state(("w",)), 1, 1.1)
        self.assertIsNone(stick.next_event(1.5, 1.5, held=True, pending=True))
        self.assertEqual(stick.next_event(1.51, 1.51, held=True).action, 1)
