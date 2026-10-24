import unittest
from dataclasses import replace

from motor_worker.policy import ActionChunk, GamepadState, KeyboardMouseState, PolicyFrame
from motor_worker.protocol import ProtocolError
from motor_worker.session import SessionConfig
from motor_worker.stick_execution import StickExecution, StickPolicySession, StickProfile
from motor_worker.virtual_stick import StickGeometry

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
GEOMETRY = StickGeometry(320, 180, 60, 130, 20)


class StickExecutionTests(unittest.TestCase):
    def frame(self, sequence=1, received_at=1):
        return PolicyFrame(EPOCH, sequence, received_at, 320, 180, bytes(320 * 180 * 3))

    def chunk(self, x=0, y=1):
        state = replace(GamepadState.neutral(), left=(x, y))
        return ActionChunk((state,) * 18, 60)

    def test_five_hz_corrections_keep_one_contact_then_expire(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        held, events = False, []
        for index in range(10):
            now = 1 + index * 0.2
            frame = self.frame(index + 1, now)
            execution.scene(frame, True, now)
            self.assertTrue(execution.accept(index + 1, frame, self.chunk(index % 2 * 0.2), now))
            for offset in (0.01, 0.04, 0.08, 0.14, 0.19):
                event = execution.next_event(now + offset, now, held=held, pending=False)
                if event:
                    events.append(event)
                    execution.trajectory.sent(event, now + offset)
                    held = event.action in (0, 2)
        self.assertEqual(sum(e.action == 0 for e in events), 1)
        self.assertFalse(any(e.action == 1 for e in events))
        event = execution.next_event(3.2, 3.19, held=True, pending=False)
        self.assertEqual(event.action, 1)

    def test_wasd_neutral_moves_to_center_without_releasing(self):
        execution = StickExecution(StickProfile(GEOMETRY, "wasd"))
        held, events = False, []
        for index, keys in enumerate((("w",), (), ("w", "d"), ("w", "s"))):
            now = 1 + index * 0.2
            frame = self.frame(index + 1, now)
            execution.scene(frame, True, now)
            execution.accept(
                index + 1, frame, ActionChunk((KeyboardMouseState(keys, (), 0, 0),), 20), now
            )
            for offset in (0.01, 0.04):
                event = execution.next_event(now + offset, now, held=held, pending=False)
                if event:
                    events.append(event)
                    execution.trajectory.sent(event, now + offset)
                    held = event.action in (0, 2)
        self.assertEqual([e.action for e in events].count(0), 1)
        self.assertNotIn(1, [e.action for e in events])
        self.assertEqual((events[-1].x, events[-1].y), (60, 130))

    def test_unknown_scene_releases_and_rejects_old_inference_after_resume(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        first = self.frame(1, 1)
        execution.scene(first, True, 1)
        execution.accept(1, first, self.chunk(), 1)
        execution.scene(self.frame(2, 1.1), False, 1.1)
        event = execution.next_event(1.11, 1.1, held=True, pending=False)
        self.assertEqual(event.action, 1)
        execution.scene(self.frame(4, 1.2), True, 1.2)
        old = self.frame(3, 1.15)
        self.assertFalse(execution.accept(2, old, self.chunk(), 1.21))
        self.assertIsNone(execution.next_event(1.22, 1.2, held=False, pending=False))
        fresh = self.frame(5, 1.3)
        execution.scene(fresh, True, 1.3)
        self.assertTrue(execution.accept(3, fresh, self.chunk(), 1.31))

    def test_no_command_queued_around_unknown_native_receipt(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        frame = self.frame()
        execution.scene(frame, True, 1)
        execution.accept(1, frame, self.chunk(), 1)
        execution.scene(self.frame(2, 1.1), False, 1.1)
        self.assertIsNone(execution.next_event(1.11, 1.1, held=True, pending=True))
        self.assertEqual(execution.next_event(1.2, 1.1, held=True, pending=False).action, 1)

    def test_result_age_cannot_be_hidden_by_a_fresh_video(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        old = self.frame(1, 1)
        execution.scene(old, True, 1)
        execution.scene(self.frame(2, 1.5), True, 1.5)
        self.assertFalse(execution.accept(1, old, self.chunk(), 1.5))
        self.assertIsNone(execution.next_event(1.51, 1.5, held=False, pending=False))

    def test_stale_scene_stops_even_when_video_is_fresh(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        frame = self.frame()
        execution.scene(frame, True, 1)
        execution.accept(1, frame, self.chunk(), 1)
        self.assertEqual(execution.next_event(1.31, 1.3, held=True, pending=False).action, 1)

    def test_foreign_epoch_and_geometry_refuse_before_execution(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        execution.scene(self.frame(), True, 1)
        for frame in (
            replace(self.frame(2, 1.1), capture_epoch="0b59dcba-444f-4daa-9a22-aa1b1294ed98"),
            PolicyFrame(EPOCH, 2, 1.1, 321, 180, bytes(321 * 180 * 3)),
        ):
            with self.assertRaises(ProtocolError):
                execution.scene(frame, True, 1.1)

    def test_unmapped_buttons_require_explicit_mask_and_are_counted(self):
        state = replace(GamepadState.neutral(), right=(0.2, 0))
        chunk = ActionChunk((state,) * 18, 60)
        for masking in (False, True):
            execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left", masking))
            execution.scene(self.frame(), True, 1)
            if masking:
                self.assertTrue(execution.accept(1, self.frame(), chunk, 1))
                self.assertEqual(execution.masked, 1)
            else:
                with self.assertRaisesRegex(ProtocolError, "unmapped_stick_channels"):
                    execution.accept(1, self.frame(), chunk, 1)

    def test_wasd_rejects_mouse_and_non_wasd_keys_by_default(self):
        execution = StickExecution(StickProfile(GEOMETRY, "wasd"))
        execution.scene(self.frame(), True, 1)
        chunk = ActionChunk((KeyboardMouseState(("w",), (), 5, 0),), 20)
        with self.assertRaisesRegex(ProtocolError, "unmapped_stick_channels"):
            execution.accept(1, self.frame(), chunk, 1)

    def test_duplicate_result_and_unobserved_frame_cannot_execute(self):
        execution = StickExecution(StickProfile(GEOMETRY, "gamepad_left"))
        execution.scene(self.frame(), True, 1)
        execution.accept(1, self.frame(), self.chunk(), 1)
        for args in (
            (1, self.frame(), self.chunk(), 1.01),
            (2, self.frame(3, 1.01), self.chunk(), 1.02),
        ):
            with self.assertRaises(ProtocolError):
                execution.accept(*args)

    def test_session_requires_explicit_execution_and_scene_guard(self):
        config = SessionConfig(
            "http://127.0.0.1:3015", EPOCH, probe_control=True, shadow_policy=True
        )
        for changes in ({"execution_enabled": False}, {"scene_guard": None}):
            kwargs = dict(
                profile=StickProfile(GEOMETRY, "gamepad_left"),
                policy=object(),
                scene_guard=lambda frame: True,
                execution_enabled=True,
            )
            kwargs.update(changes)
            with self.assertRaises(ProtocolError):
                StickPolicySession(config, **kwargs)
