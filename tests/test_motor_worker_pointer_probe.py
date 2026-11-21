"""Opt-in pointer authority, exact receipts and freshness boundaries; no codecs."""

import json
import unittest
from types import SimpleNamespace as NS

from motor_worker.pointer_probe import PointerProbe, ProbePoint
from motor_worker.protocol import ControlAdmission, InputAvailability, ProtocolError
from motor_worker.session import HeadlessSession, SessionConfig
from tests.test_motor_worker_protocol import CAPTURE, EPOCH, SESSION, identity, receipt


class PointerProbeTests(unittest.TestCase):
    def probe(self):
        return PointerProbe(960, 540, (ProbePoint(0, 0, 100, 100), ProbePoint(1000, 1, 120, 100)))

    def admission(self, enabled=True):
        p = ControlAdmission(SESSION, CAPTURE, allow_pointer=enabled)
        p.receive(identity(), 1)
        p.receive(receipt(), 1)
        return p

    def applied(self, seq, action):
        d = json.loads(receipt("applied", seq, action))
        d["gesture"] = 1
        return json.dumps(d)

    def test_disabled_input_cannot_emit_down_even_after_native_ready(self):
        p = self.admission(False)
        with self.assertRaisesRegex(ProtocolError, "pointer_not_admitted"):
            p.pointer(0, 100, 100, 2)
        self.assertEqual(p.pointer_commands, 0)

    def test_exact_ack_hold_and_heartbeat_gesture_then_release(self):
        p = self.admission()
        d = p.pointer(0, 100, 100, 2)
        self.assertEqual((d["sequence"], d["gesture"]), (1, 1))
        with self.assertRaises(ProtocolError):
            p.pointer(2, 120, 100, 2.01)
        with self.assertRaises(ProtocolError):
            p.receive(self.applied(2, 0), 2.02)
        p.receive(self.applied(1, 0), 2.02)
        self.assertTrue(p.held)
        hb = p.heartbeat(2.3)
        self.assertEqual(hb["gesture"], 1)
        d = json.loads(receipt("alive", 2))
        d["gesture"] = 1
        p.receive(json.dumps(d), 2.31)
        p.pointer(1, 100, 100, 2.5)
        p.receive(self.applied(3, 1), 2.52)
        self.assertFalse(p.held)
        self.assertEqual(p.applied_receipts, 2)

    def test_unknown_input_deadline_never_becomes_an_idle_alive(self):
        p = self.admission()
        p.pointer(0, 100, 100, 2)
        with self.assertRaises(ProtocolError):
            p.receive(receipt("alive", 1), 2.1)
        with self.assertRaisesRegex(ProtocolError, "control_action_deadline"):
            p.heartbeat(2.5)
        self.assertEqual(p.pointer_commands, 1)

    def test_exact_inflight_pointer_ack_can_drain_during_close_but_cannot_send_more(self):
        p = self.admission()
        p.pointer(0, 100, 100, 2)
        p.close_message()
        p.receive(self.applied(1, 0), 2.1)
        self.assertEqual(p.applied_receipts, 1)
        self.assertFalse(p.ready)
        with self.assertRaises(ProtocolError):
            p.pointer(2, 110, 110, 2.2)
        p.receive(receipt("closed", action=3), 2.3)
        self.assertFalse(p.held)
        self.assertTrue(p.closed)

    def test_parser_bounds_shape_time_order_and_coordinates_before_transport(self):
        base = dict(
            schema_version=1,
            frame_width=960,
            frame_height=540,
            points=[dict(t_ms=0, action=0, x=1, y=2), dict(t_ms=1000, action=1, x=1, y=2)],
        )
        self.assertEqual(PointerProbe.parse(json.dumps(base)).points[-1].at_ms, 1000)
        for changed in [
            dict(schema_version=True),
            dict(extra=1),
            dict(frame_width=0),
            dict(points=base["points"] * 40),
            dict(points=[base["points"][0], dict(t_ms=5001, action=1, x=1, y=2)]),
            dict(points=[base["points"][0], dict(t_ms=1, action=1, x=960, y=2)]),
            dict(points=[base["points"][0], dict(t_ms=1, action=2, x=1, y=2)]),
        ]:
            with self.subTest(changed=changed), self.assertRaises(ProtocolError):
                PointerProbe.parse(json.dumps(base | changed))

    def test_probe_requires_explicit_control_and_enough_finite_run_time(self):
        for options in [dict(probe_control=False), dict(probe_control=True, duration=1)]:
            with self.assertRaisesRegex(ProtocolError, "invalid_pointer_probe_budget"):
                SessionConfig("http://localhost", EPOCH, pointer_probe=self.probe(), **options)

    def test_stale_receiver_frame_never_causes_down(self):
        session = HeadlessSession(
            SessionConfig(
                "http://localhost",
                EPOCH,
                duration=3,
                probe_control=True,
                pointer_probe=self.probe(),
            )
        )
        session.admission = self.admission()
        session.availability = InputAvailability(SESSION)
        session.availability.receive(
            dict(
                type="input_availability",
                schema_version=1,
                session_id=SESSION,
                capture_epoch=EPOCH,
                revision=0,
                state="manual",
                task_id=None,
            )
        )
        session.frames.latest = NS(received_at=1, receiver_sequence=1)
        with self.assertRaisesRegex(ProtocolError, "pointer_probe_receiver_frame_stale"):
            session._tick_pointer_probe(2)
        self.assertEqual(session.admission.pointer_commands, 0)


if __name__ == "__main__":
    unittest.main()
