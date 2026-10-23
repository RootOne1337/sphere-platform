import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from motor_worker.protocol import ProtocolError, VideoBinding
from motor_worker.teach import inspect_capture
from motor_worker.teach_capture import (
    TeachBudget,
    TeachCapture,
    capture_units,
    nal_types,
    validate_capture,
    validate_inputs,
)

DEVICE = "753fd530-2f19-4e5e-98ba-769863678141"
EPISODE = "f3867238-d651-4ce0-9e71-e892ce6e28fb"
PROFILE = "7be1db61-acab-4c6b-8bea-b5330594fdcf"
IDR = b"\0\0\0\1\x67\x42\x00\x1f\0\0\1\x68\xaa\0\0\1\x65\xab"
DELTA = b"\0\0\1\x41\xab"


class TeachCaptureTests(unittest.TestCase):
    def test_annexb_prefix_boundaries_and_nal_quota(self):
        self.assertEqual(nal_types(IDR), (7, 8, 5))
        self.assertEqual(nal_types(b"\0\0\1\x65"+b"\xab"*(2*1024*1024-4)), (5,))
        for payload in (b"x"+IDR, b"\0\0\0\1", b"\0\0\1\xe5", DELTA*65):
            with self.assertRaises(ProtocolError):
                nal_types(payload)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()/"capture"
        self.sinks = []
        self.addCleanup(self.retire)

    def retire(self):
        for sink in self.sinks:
            sink.finish(transport_success=False, input_released=False)

    def new(self, **kwargs):
        sink = TeachCapture(self.root, device_id=DEVICE, episode_id=EPISODE,
                            profile_revision=PROFILE, clock=lambda: 10.0, **kwargs)
        sink.bind(VideoBinding(EPISODE, 480, 270))
        self.sinks.append(sink)
        return sink

    def populate(self, sink):
        self.assertTrue(sink.offer_access_unit(IDR, 4294964296, 10.0))
        self.assertTrue(sink.offer_access_unit(DELTA, 0, 10.034))

    def command(self, sequence, action):
        return dict(type="touch_event", sequence=sequence, gesture=1, action=action, x=80, y=200)

    def receipt(self, sequence, action):
        return dict(type="shared_input_status", capture_epoch=EPISODE, sequence=sequence,
                    gesture=1, action=action, outcome="applied", device_uptime_ms=100+sequence)

    def test_exact_payload_rtp_wrap_and_video_only_are_preserved(self):
        sink = self.new()
        self.populate(sink)
        result = sink.finish(transport_success=True, input_released=False)
        self.assertTrue(result["complete"], result)
        self.assertTrue(result["writer_retired"])
        self.assertFalse(result["native_clock_mapping_known"])
        manifest = validate_capture(self.root)
        self.assertEqual(manifest["purpose"], "video_only")
        self.assertEqual((self.root/"video.h264").read_bytes(), IDR+DELTA)
        units = list(capture_units(self.root, manifest))
        self.assertEqual([v[0]["rtp_ticks"] for v in units], [0, 3000])
        self.assertEqual(inspect_capture(self.root)["frames"], 2)
        self.assertIs(result, sink.finish(transport_success=False, input_released=False))

    def test_delta_before_self_contained_idr_is_not_written(self):
        sink = self.new()
        self.assertTrue(sink.offer_access_unit(DELTA, 7, 10.0))
        self.assertTrue(sink.offer_access_unit(IDR, 3007, 10.1))
        self.assertTrue(sink.finish(transport_success=True, input_released=False)["complete"])
        self.assertEqual((self.root/"video.h264").read_bytes(), IDR)

    def test_submissions_and_native_receipts_are_separate_sanitized_events(self):
        sink = self.new()
        self.populate(sink)
        for sequence, action in ((1, 0), (2, 2), (3, 1)):
            self.assertTrue(sink.command(self.command(sequence, action), 10+sequence/10))
            receipt = self.receipt(sequence, action) | {"owner": "private-owner", "token": "private-token"}
            self.assertTrue(sink.receipt(receipt, 10+sequence/10+0.02))
        self.assertTrue(sink.finish(transport_success=True, input_released=True)["complete"])
        manifest = validate_capture(self.root)
        self.assertEqual(validate_inputs(self.root, manifest), dict(commands=3, applied=3, complete=True))
        raw = (self.root/"inputs.jsonl").read_text()
        self.assertNotIn("private", raw)
        self.assertIn('"device_uptime_ms"', raw)
        self.assertNotIn("capture_age", raw)

    def test_input_uncertainty_never_creates_complete_marker(self):
        sink = self.new()
        self.populate(sink)
        self.assertTrue(sink.command(self.command(1, 0), 10.1))
        self.assertFalse(sink.finish(transport_success=True, input_released=True)["complete"])
        self.assertFalse((self.root/"COMPLETE").exists())
        with self.assertRaises(ProtocolError):
            validate_capture(self.root)

    def test_held_contact_needs_terminal_or_confirmed_native_close(self):
        sink = self.new()
        self.populate(sink)
        self.assertTrue(sink.command(self.command(1, 0), 10.1))
        self.assertTrue(sink.receipt(self.receipt(1, 0), 10.12))
        self.assertTrue(sink.receipt(dict(type="shared_input_status", capture_epoch=EPISODE,
                                          sequence=0, outcome="closed", device_uptime_ms=999), 10.2))
        self.assertTrue(sink.finish(transport_success=True, input_released=True)["complete"])
        self.assertEqual(validate_inputs(self.root, validate_capture(self.root))["applied"], 1)

    def test_changed_capture_or_duplicate_pts_abort(self):
        sink = self.new()
        self.populate(sink)
        self.assertFalse(sink.offer_access_unit(DELTA, 0, 10.04))
        self.assertFalse(sink.finish(transport_success=True, input_released=False)["complete"])

    def test_bounded_queue_never_silently_drops_old_training_frames(self):
        release = threading.Event()
        original = TeachCapture._write

        def blocked(sink):
            release.wait(2)
            original(sink)

        with patch.object(TeachCapture, "_write", blocked):
            sink = self.new()
            try:
                for i in range(32):
                    self.assertTrue(sink.offer_access_unit(IDR if i == 0 else DELTA, i*3000, 10+i/30))
                self.assertFalse(sink.offer_access_unit(DELTA, 96000, 11.1))
                self.assertEqual(sink.failure, "teach_writer_backpressure")
            finally:
                release.set()
                result = sink.finish(transport_success=True, input_released=False)
        self.assertFalse(result["complete"])
        self.assertTrue(result["writer_retired"])
        self.assertFalse((self.root/"COMPLETE").exists())

    def test_payload_corruption_is_detected_before_reading_features(self):
        sink = self.new()
        self.populate(sink)
        sink.finish(transport_success=True, input_released=False)
        (self.root/"video.h264").write_bytes(IDR+DELTA[:-1]+b"z")
        with self.assertRaisesRegex(ProtocolError, "teach_artifact_integrity"):
            validate_capture(self.root)

    def test_boolean_schema_and_unexpected_files_are_refused(self):
        sink = self.new()
        self.populate(sink)
        sink.finish(transport_success=True, input_released=False)
        data = json.loads((self.root/"manifest.json").read_text())
        data["schema_version"] = True
        raw = json.dumps(data).encode()
        (self.root/"manifest.json").write_bytes(raw)
        (self.root/"COMPLETE").write_bytes(hashlib.sha256(raw).hexdigest().encode()+b"\n")
        with self.assertRaisesRegex(ProtocolError, "teach_invalid_manifest"):
            validate_capture(self.root)

    def test_existing_output_and_bad_identity_are_never_overwritten(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):
            self.new()
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(ProtocolError):
            TeachBudget(frames=True)
        with self.assertRaises(ProtocolError):
            TeachBudget(bytes=99999999999)
