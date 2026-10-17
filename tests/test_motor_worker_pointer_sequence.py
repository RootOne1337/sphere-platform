import unittest

from motor_worker.pointer_probe import ProbePoint
from motor_worker.pointer_sequence import PointerSequence, PointerSequenceClock
from motor_worker.protocol import ProtocolError


class PointerSequenceTests(unittest.TestCase):
    def test_double_tap_has_two_exact_gestures_and_a_final_release(self):
        clock = PointerSequenceClock(PointerSequence.double_tap(960, 540, 900, 475))
        held, events = False, []
        for tick in range(20):
            point = clock.reserve(1 + tick * 0.02, held=held, pending=False, frame_age=0.02)
            if point:
                events.append(point.action)
                held = point.action != 1
        self.assertEqual(events, [0, 1, 0, 1])
        self.assertFalse(held)

    def test_camera_drag_is_continuous_then_released(self):
        plan = PointerSequence.camera_drag(960, 540, (700, 270), (580, 270))
        self.assertEqual([point.action for point in plan.points], [0, 2, 2, 2, 2, 2, 2, 1])
        self.assertEqual((plan.points[-1].x, plan.points[-1].y), (580, 270))

    def test_unknown_ack_never_reserves_a_second_edge(self):
        clock = PointerSequenceClock(PointerSequence.double_tap(960, 540, 900, 475))
        self.assertEqual(clock.reserve(1, held=False, pending=False, frame_age=0.01).action, 0)
        for at in (1.01, 1.05, 1.1):
            self.assertIsNone(clock.reserve(at, held=False, pending=True, frame_age=0.01))
        self.assertEqual(clock.index, 1)

    def test_delayed_callback_refuses_to_replay_a_tap(self):
        clock = PointerSequenceClock(PointerSequence.double_tap(960, 540, 900, 475))
        clock.reserve(1, held=False, pending=False, frame_age=0.01)
        with self.assertRaisesRegex(ProtocolError, "deadline"):
            clock.reserve(1.5, held=True, pending=False, frame_age=0.01)
        self.assertEqual(clock.index, 1)

    def test_stale_frame_and_native_state_mismatch_fail_without_sending(self):
        clock = PointerSequenceClock(PointerSequence.double_tap(960, 540, 900, 475))
        with self.assertRaisesRegex(ProtocolError, "frame_stale"):
            clock.reserve(1, held=False, pending=False, frame_age=0.4)
        with self.assertRaisesRegex(ProtocolError, "native_state_mismatch"):
            clock.reserve(1, held=True, pending=False, frame_age=0.01)
        self.assertEqual(clock.index, 0)

    def test_unreleased_reordered_and_out_of_bounds_plans_are_refused(self):
        for points in (
            (ProbePoint(0, 0, 1, 1), ProbePoint(50, 2, 2, 2)),
            (ProbePoint(0, 0, 1, 1), ProbePoint(0, 1, 1, 1)),
            (ProbePoint(0, 0, 1, 1), ProbePoint(50, 1, 960, 1)),
        ):
            with self.assertRaises(ProtocolError):
                PointerSequence(960, 540, points)
