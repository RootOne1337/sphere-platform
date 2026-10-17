"""Identity, freshness and bounded lifecycle regressions; no network/codecs."""

import unittest
from fractions import Fraction
from types import SimpleNamespace as NS

from motor_worker.observation import LatestFrame
from motor_worker.protocol import (
    ControlAdmission,
    InputAvailability,
    ProtocolError,
    VideoBinding,
    message,
    selected_route,
    signaling_url,
    validate_sdp,
    wire_offer,
)
from motor_worker.session import SessionConfig

SESSION = "a" * 32
OWNER = "b" * 32
EPOCH = "753fd530-2f19-4e5e-98ba-769863678141"
CAPTURE = VideoBinding(EPOCH, 960, 540)


def receipt(outcome="ready", sequence=0, action=4, **kwargs):
    import json

    return json.dumps(
        dict(
            type="shared_input_status",
            session_id=SESSION,
            owner=OWNER,
            capture_epoch=EPOCH,
            sequence=sequence,
            action=action,
            gesture=0,
            outcome=outcome,
            device_uptime_ms=4200,
            **kwargs,
        )
    )


def identity(**kwargs):
    import json

    d = dict(
        type="touch_session",
        session_id=SESSION,
        owner=OWNER,
        capture_epoch=EPOCH,
        frame_width=960,
        frame_height=540,
    )
    d.update(kwargs)
    return json.dumps(d)


def sdp(direction="recvonly"):
    return (
        "\r\n".join(
            [
                "v=0",
                "m=video 9 UDP/TLS/RTP/SAVPF 102",
                f"a={direction}",
                "a=rtpmap:102 H264/90000",
                "a=fingerprint:sha-256 " + ":".join(["AB"] * 32),
                "m=application 9 UDP/DTLS/SCTP webrtc-datachannel",
            ]
        )
        + "\r\n"
    )


class ProtocolTests(unittest.TestCase):
    def test_availability_before_video_is_bound_later_and_never_grants_native_ready(self):
        p = InputAvailability(SESSION)
        d = dict(
            type="input_availability",
            schema_version=1,
            session_id=SESSION,
            capture_epoch=EPOCH,
            revision=0,
            state="manual",
            task_id=None,
        )
        p.receive(d)
        p.bind(EPOCH)
        p.receive(d)
        self.assertEqual(p.state, "manual")
        self.assertFalse(ControlAdmission(SESSION, CAPTURE).ready)

    def test_foreign_stale_and_conflicting_availability_cannot_reopen_input(self):
        p = InputAvailability(SESSION)
        p.bind(EPOCH)
        d = dict(
            type="input_availability",
            schema_version=1,
            session_id=SESSION,
            capture_epoch=EPOCH,
            revision=2,
            state="automation",
            task_id="owned-task-1234",
        )
        p.receive(d)
        for changed in [
            dict(revision=1),
            dict(state="manual", task_id=None),
            dict(session_id=OWNER),
            dict(capture_epoch=SESSION),
            dict(schema_version=True),
            dict(state=[]),
            dict(state="manual"),
            dict(task_id=None),
            dict(extra=1),
        ]:
            with self.subTest(changed=changed), self.assertRaises(ProtocolError):
                p.receive(d | changed)
        self.assertEqual(p.state, "automation")
        p.receive(d | dict(revision=3, state="manual", task_id=None))
        self.assertEqual(p.state, "manual")

    def test_availability_first_snapshot_cannot_change_capture_after_video_binding(self):
        p = InputAvailability(SESSION)
        p.receive(
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
        with self.assertRaisesRegex(ProtocolError, "foreign_availability_capture"):
            p.bind("414ce0e9-4b93-4f96-b9ca-ee675f53835e")

    def test_only_tls_or_local_plaintext_and_canonical_device_identity(self):
        self.assertEqual(
            signaling_url("http://127.0.0.1:3015", EPOCH),
            f"ws://127.0.0.1:3015/ws/direct-probe/{EPOCH}",
        )
        self.assertTrue(signaling_url("https://example.test", EPOCH).startswith("wss://"))
        for base in [
            "http://192.168.1.1",
            "https://user:secret@example.test",
            "https://x/?token=secret",
            "https://x/a",
            "https://x/#fragment",
            "file:///c:/x",
            "https://x:99999",
        ]:
            with self.subTest(base=base), self.assertRaises(ProtocolError):
                signaling_url(base, EPOCH)
        with self.assertRaises(ProtocolError):
            signaling_url("https://x", "PH030")

    def test_budget_rejects_nan_infinity_boolean_and_unbounded_runs(self):
        for value in [float("nan"), float("inf"), 0, 301, True]:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                SessionConfig("http://localhost", EPOCH, duration=value)

    def test_wire_offer_keeps_real_sha256_without_exposing_other_fingerprints(self):
        source = sdp() + "a=fingerprint:sha-384 " + ":".join(["CD"] * 48) + "\r\n"
        with self.assertRaises(ProtocolError):
            validate_sdp(source, offer=True)
        prepared = wire_offer(source)
        self.assertIn(":".join(["AB"] * 32), prepared)
        self.assertNotIn("sha-384", prepared)
        self.assertEqual(validate_sdp(prepared, offer=True), prepared)

    def test_media_permissions_and_relay_candidates_are_not_silently_accepted(self):
        for source in [
            sdp("sendrecv"),
            sdp() + "m=audio 9 UDP/TLS/RTP/SAVPF 0\r\n",
            sdp() + "a=candidate:x 1 udp 1 1.2.3.4 5 typ relay\r\n",
        ]:
            with self.subTest(source=source), self.assertRaises(ProtocolError):
                validate_sdp(source, offer=True)

    def test_h264_receive_level_changes_only_constrained_baseline_fmtp(self):
        source = (
            sdp()
            + "a=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f\r\n"
        )
        source += "a=fmtp:120 profile-level-id=42e01f\r\n"
        result = wire_offer(source)
        self.assertIn("profile-level-id=42e02a", result)
        self.assertIn("a=fmtp:120 profile-level-id=42e01f", result)

    def test_receive_only_offer_does_not_announce_a_nonexistent_source(self):
        source = sdp() + "a=ssrc:123 cname:unused\r\na=msid:unused track\r\n"
        result = wire_offer(source)
        self.assertNotIn("a=ssrc:", result)
        self.assertNotIn("a=msid:", result)
        self.assertIn("a=recvonly", result)

    def test_binding_requires_exact_session_uuid_and_bounded_picture(self):
        self.assertEqual(VideoBinding.parse(f"SV1 {SESSION} {EPOCH} 960 540", SESSION), CAPTURE)
        for raw in [
            f"SV1 {OWNER} {EPOCH} 960 540",
            f"SV1 {SESSION} {EPOCH} 8192 8192",
            f"SV1 {SESSION} 00000000-0000-0000-0000-000000000000 1 1",
            b"wire",
        ]:
            with self.assertRaises(ProtocolError):
                VideoBinding.parse(raw, SESSION)

    def test_json_is_bounded_and_duplicate_keys_cannot_change_identity(self):
        for raw in ['{"owner":"a","owner":"b"}', "[]", "[" * 2000, "x" * 1025, b"{}"]:
            with self.assertRaises(ProtocolError):
                message(raw, 1024)

    def test_identity_alone_does_not_grant_native_ready(self):
        p = ControlAdmission(SESSION, CAPTURE)
        p.receive(identity(), 1)
        self.assertFalse(p.ready)
        self.assertIsNone(p.heartbeat(2))
        p.receive(receipt(), 2)
        self.assertTrue(p.ready)
        command = p.heartbeat(3)
        self.assertEqual(command["action"], 4)
        self.assertEqual(command["gesture"], 0)
        p.receive(receipt("alive", 1), 3.012)
        self.assertAlmostEqual(p.last_actor_rtt_ms, 12)
        self.assertEqual(p.alive_receipts, 1)

    def test_foreign_owner_or_capture_cannot_confirm_admission(self):
        import json

        for field in ["owner", "session_id", "capture_epoch"]:
            p = ControlAdmission(SESSION, CAPTURE)
            p.receive(identity(), 1)
            d = json.loads(receipt())
            d[field] = "wrong"
            with self.assertRaises(ProtocolError):
                p.receive(json.dumps(d), 2)
            self.assertFalse(p.ready)

    def test_one_pending_alive_and_its_exact_receipt_are_required(self):
        p = ControlAdmission(SESSION, CAPTURE)
        p.receive(identity(), 1)
        p.receive(receipt(), 1)
        p.heartbeat(2)
        self.assertIsNone(p.heartbeat(2.5))
        with self.assertRaisesRegex(ProtocolError, "control_alive_deadline"):
            p.heartbeat(3)
        with self.assertRaises(ProtocolError):
            p.receive(receipt("alive", 2), 3)

    def test_unsolicited_applied_cannot_be_mistaken_for_idle_liveness(self):
        p = ControlAdmission(SESSION, CAPTURE)
        p.receive(identity(), 1)
        p.receive(receipt(), 1)
        p.heartbeat(2)
        with self.assertRaises(ProtocolError):
            p.receive(receipt("applied", 1), 3)
        self.assertEqual(p.alive_receipts, 0)

    def test_close_before_identity_accepts_exact_closed_but_never_late_ready(self):
        p = ControlAdmission(SESSION, CAPTURE)
        p.close_message()
        p.receive(identity(), 1)
        with self.assertRaises(ProtocolError):
            p.receive(receipt(), 2)
        p.receive(receipt("closed", action=3), 3)
        self.assertTrue(p.closed)
        self.assertFalse(p.ready)

    def test_exact_pending_alive_can_drain_after_close_begins_without_reopening(self):
        p = ControlAdmission(SESSION, CAPTURE)
        p.receive(identity(), 1)
        p.receive(receipt("ready"), 1)
        event = p.heartbeat(1.2)
        p.close_message()
        with self.assertRaises(ProtocolError):
            p.receive(receipt("alive", event["sequence"] + 1), 1.25)
        p.receive(receipt("alive", event["sequence"]), 1.3)
        self.assertFalse(p.ready)
        self.assertTrue(p.closing)
        self.assertIsNone(p.pending)
        self.assertIsNone(p.heartbeat(1.4))
        p.receive(receipt("closed", action=3), 1.5)
        self.assertTrue(p.closed)
        with self.assertRaises(ProtocolError):
            p.receive(receipt("alive", event["sequence"]), 1.6)
        self.assertFalse(p.ready)

    def test_denied_unknown_and_expired_are_never_ready(self):
        for reason in ["denied", "unknown", "expired", "invalid", "busy"]:
            p = ControlAdmission(SESSION, CAPTURE)
            p.receive(identity(), 1)
            p.receive(receipt(reason), 2)
            self.assertEqual(p.failure, "control_" + reason)
            with self.assertRaises(ProtocolError):
                p.receive(receipt(), 3)

    def test_non_string_outcome_is_rejected_without_callback_typeerror(self):
        import json

        p = ControlAdmission(SESSION, CAPTURE)
        p.receive(identity(), 1)
        data = json.loads(receipt())
        data["outcome"] = {"ready": True}
        with self.assertRaises(ProtocolError):
            p.receive(json.dumps(data), 2)
        self.assertFalse(p.ready)

    def test_latest_slot_does_not_reuse_duplicate_or_stale_pts(self):
        slot = LatestFrame()
        for pts in [100, 200, 300]:
            slot.put(NS(pts=pts, time_base=Fraction(1, 90000)), pts / 100)
        self.assertEqual(slot.take(3).pts, 300)
        self.assertIsNone(slot.take(3.1))
        self.assertFalse(slot.put(NS(pts=300, time_base=Fraction(1, 90000)), 3.1))
        slot.put(NS(pts=400, time_base=Fraction(1, 90000)), 4)
        self.assertIsNone(slot.take(6))
        slot.clear()
        self.assertIsNone(slot.latest)

    def test_unknown_pts_or_changed_clock_cannot_become_fresh_observation(self):
        slot = LatestFrame()
        self.assertFalse(slot.put(NS(pts=None, time_base=None), 1))
        slot.put(NS(pts=1, time_base=Fraction(1, 90000)), 1)
        self.assertFalse(slot.put(NS(pts=2, time_base=Fraction(1, 1000)), 2))

    def test_route_uses_nominated_pair_and_does_not_claim_lan(self):
        pair = NS(
            local_candidate=NS(type="host", host="192.168.1.2", transport="udp"),
            remote_candidate=NS(type="srflx", host="203.0.113.5", transport="udp"),
        )
        peer = NS(sctp=NS(transport=NS(transport=NS(_connection=NS(_nominated={1: pair})))))
        route = selected_route(peer)
        self.assertEqual(route["path"], "nat")
        self.assertFalse(route["lanProven"])
        self.assertNotIn("192.168.1.2", str(route))
        self.assertEqual(selected_route(NS())["path"], "unknown")
        peer.sctp.transport.transport._connection._nominated = {}
        self.assertEqual(selected_route(peer)["path"], "unknown")


if __name__ == "__main__":
    unittest.main()
