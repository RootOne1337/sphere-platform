"""Real codec fixtures and negative boundaries for the offline browser importer."""

import hashlib
import json
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import av
import numpy as np
from PIL import Image

from motor_worker.browser_teach import (
    MIB,
    browser_units,
    inspect_browser,
    prepare_browser,
    validate_browser,
)
from motor_worker.protocol import ProtocolError
from motor_worker.teach_capture import nal_types

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
CLIP = "a"*32


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, allow_nan=False)+"\n").encode()


class BrowserTeachTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name).resolve()
        self.source = self.parent/"source"
        self.source.mkdir()
        codec = av.CodecContext.create("libx264", "w")
        codec.width, codec.height, codec.pix_fmt = 96, 64, "yuv420p"
        codec.time_base = Fraction(1, 30)
        codec.options = {"preset": "ultrafast", "tune": "zerolatency"}
        packets = []
        for i in range(16):
            array = np.random.default_rng(i).integers(0, 256, (64, 96, 3), np.uint8)
            frame = av.VideoFrame.from_ndarray(array, format="rgb24")
            frame.pts = i
            packets.extend(codec.encode(frame))
        packets.extend(codec.encode(None))
        self.frames = []
        video = bytearray()
        for index, packet in enumerate(packets):
            data = bytes(packet)
            types = set(nal_types(data))
            self.frames.append(dict(index=index, offset=len(video), bytes=len(data),
                rtp_timestamp=(2**32-3000+index*3000) % 2**32, relative_ticks_90k=index*3000,
                worker_observed_at_ms=1100+index*34, key=5 in types,
                seekable={5, 7, 8}.issubset(types), sha256=digest(data)))
            video.extend(data)
        (self.source/"video.h264").write_bytes(video)
        self.inputs = []
        for sequence, action in [(1, 0), (2, 1)]:
            event = dict(stage="submitted", at_ms=1150+sequence*10, sequence=sequence,
                         gesture=1, action=action, pointer_id=0, x=40, y=50)
            self.inputs += [event, event | dict(stage="receipt", at_ms=event["at_ms"]+1,
                                               outcome="applied", device_uptime_ms=100+sequence)]
        self.inputs.append(dict(stage="closed", at_ms=1800, sequence=0, gesture=0, action=3,
                                pointer_id=-1, outcome="closed", device_uptime_ms=200,
                                cancelled_pointers=[]))
        self.manifest = dict(schema="sphere-browser-teaching-v2", id=CLIP,
            config=dict(id=CLIP, device_id=EPOCH, capture_epoch=EPOCH,
                        width=96, height=64, source="direct_webrtc_h264", profile={"mode": "stick"}),
            started_at_ms=1000, finalized_at_ms=2000, complete=True, release_confirmed=True,
            failure=None, frames=len(self.frames), events=len(self.inputs), files={},
            media_duration_ticks_90k=self.frames[-1]["relative_ticks_90k"])
        self.seal()

    def seal(self):
        for name, rows in (("frames.jsonl", self.frames), ("inputs.jsonl", self.inputs)):
            raw = b"".join(encode(row) for row in rows)
            (self.source/name).write_bytes(raw)
            self.manifest["files"][name] = dict(bytes=len(raw), sha256=digest(raw))
        self.manifest["events"] = len(self.inputs)
        self.manifest["files"]["video.h264"] = dict(bytes=(self.source/"video.h264").stat().st_size)
        raw = encode(self.manifest)
        (self.source/"manifest.json").write_bytes(raw)
        (self.source/"COMPLETE").write_bytes(encode(dict(manifest_sha256=digest(raw))))

    def test_actual_h264_and_wrapped_rtp_are_verified_without_capture_latency_claim(self):
        report = inspect_browser(self.source)
        self.assertEqual(report["frames"], 16)
        self.assertEqual(report["geometry"], (96, 64))
        self.assertFalse(report["source_capture_clock_mapping_known"])
        self.assertFalse(report["execution_qualified"])
        self.assertAlmostEqual(report["media_fps"], 30)

    def test_v1_legacy_closed_without_native_clock_remains_readable(self):
        self.manifest["schema"] = "sphere-browser-teaching-v1"
        self.manifest.pop("media_duration_ticks_90k")
        self.inputs[-1].pop("device_uptime_ms")
        self.inputs[-1].pop("cancelled_pointers")
        self.seal()
        self.assertEqual(inspect_browser(self.source)["frames"], 16)

    def test_hash_and_completion_failure_do_not_repair_the_source(self):
        before = (self.source/"video.h264").read_bytes()
        (self.source/"COMPLETE").write_bytes(encode(dict(manifest_sha256="0"*64)))
        with self.assertRaisesRegex(ProtocolError, "completion_hash"):
            validate_browser(self.source)
        self.assertEqual((self.source/"video.h264").read_bytes(), before)

    def test_incomplete_unreleased_or_nonfinite_source_is_rejected(self):
        for key, value in (("complete", False), ("release_confirmed", False), ("frames", True)):
            old = self.manifest[key]
            self.manifest[key] = value
            self.seal()
            with self.assertRaises(ProtocolError):
                validate_browser(self.source)
            self.manifest[key] = old
        self.seal()
        raw = (self.source/"manifest.json").read_bytes().replace(b'"started_at_ms": 1000', b'"started_at_ms": NaN')
        (self.source/"manifest.json").write_bytes(raw)
        with self.assertRaises(ProtocolError):
            validate_browser(self.source)

    def test_geometry_extent_clock_and_keyframe_metadata_are_not_trusted(self):
        mutations = [("offset", 1), ("relative_ticks_90k", 1), ("rtp_timestamp", 1), ("key", False)]
        for field, value in mutations:
            old = self.frames[0][field]
            self.frames[0][field] = value
            self.seal()
            with self.assertRaises(ProtocolError):
                inspect_browser(self.source)
            self.frames[0][field] = old
        self.manifest["config"]["width"] = 98
        self.seal()
        with self.assertRaisesRegex(ProtocolError, "decoded_binding"):
            inspect_browser(self.source)

    def test_invalid_receipts_edges_replays_and_closed_input_are_rejected(self):
        cases = [
            lambda: self.inputs[1].update(x=41),
            lambda: self.inputs[1].update(outcome="unknown"),
            lambda: self.inputs[2].update(sequence=1),
            lambda: self.inputs[0].update(action=2),
            lambda: self.inputs[-1].update(outcome="unknown"),
            lambda: self.inputs[-1].update(cancelled_pointers=[True]),
        ]
        original = json.loads(json.dumps(self.inputs))
        for change in cases:
            self.inputs = json.loads(json.dumps(original))
            change()
            self.seal()
            with self.assertRaises(ProtocolError):
                validate_browser(self.source)

    def test_confirmed_cancel_can_close_a_held_contact_without_fabricating_up(self):
        self.inputs = self.inputs[:2]+[self.inputs[-1] | dict(cancelled_pointers=[0])]
        self.seal()
        self.assertEqual(inspect_browser(self.source)["frames"], 16)
        self.inputs[-1].pop("device_uptime_ms")
        self.seal()
        with self.assertRaisesRegex(ProtocolError, "release_unconfirmed"):
            validate_browser(self.source)

    def test_full_size_png_and_original_journals_keep_exact_lineage(self):
        before = {path.name: digest(path.read_bytes()) for path in self.source.iterdir()}
        target = self.parent/"prepared"
        report = prepare_browser(self.source, target, interval=.2)
        self.assertTrue(report["prepared"])
        self.assertFalse(report["reconstruction_qualified"])
        raw = (target/"reconstruction-input.json").read_bytes()
        self.assertEqual((target/"COMPLETE").read_text().strip(), digest(raw))
        prepared = json.loads(raw)
        self.assertIsNone(prepared["cameras"])
        self.assertIsNone(prepared["metric_scale"])
        self.assertFalse(prepared["masks_applied"])
        self.assertEqual(prepared["images"][0]["source_index"], 0)
        self.assertEqual(prepared["images"][-1]["source_index"], 15)
        for row in prepared["images"]:
            image = target/row["image"]
            self.assertEqual(digest(image.read_bytes()), row["png_sha256"])
            with Image.open(image) as frame:
                self.assertEqual(frame.size, (96, 64))
            self.assertEqual(row["source_access_unit_sha256"], self.frames[row["source_index"]]["sha256"])
        for name in ("manifest.json", "inputs.jsonl", "frames.jsonl", "COMPLETE"):
            self.assertEqual((target/"source"/name).read_bytes(), (self.source/name).read_bytes())
        self.assertEqual(before, {path.name: digest(path.read_bytes()) for path in self.source.iterdir()})

    def test_image_budget_and_corrupt_tail_leave_no_completion_marker(self):
        target = self.parent/"budget"
        with self.assertRaisesRegex(ProtocolError, "image_quota"):
            prepare_browser(self.source, target, interval=.2, max_images=2)
        self.assertFalse((target/"COMPLETE").exists())
        video = bytearray((self.source/"video.h264").read_bytes())
        video[-1] ^= 1
        (self.source/"video.h264").write_bytes(video)
        with self.assertRaisesRegex(ProtocolError, "access_unit_hash"):
            prepare_browser(self.source, self.parent/"bad-tail")
        self.assertFalse((self.parent/"bad-tail"/"COMPLETE").exists())

    def test_output_is_exclusive_and_cannot_be_inside_source(self):
        existing = self.parent/"existing"
        existing.mkdir()
        (existing/"owned").write_text("preserve")
        with self.assertRaises(FileExistsError):
            prepare_browser(self.source, existing)
        self.assertEqual((existing/"owned").read_text(), "preserve")
        with self.assertRaisesRegex(ProtocolError, "inside_source"):
            prepare_browser(self.source, self.source/"derived")
        self.assertFalse((self.source/"derived").exists())

    def test_byte_and_line_bounds_are_enforced(self):
        capture = validate_browser(self.source)
        self.assertTrue(all(len(data) <= 2*MIB for _, data in browser_units(capture)))
        self.manifest["frames"] = 36001
        self.seal()
        with self.assertRaisesRegex(ProtocolError, "row_quota"):
            validate_browser(self.source)

    def test_png_writer_cannot_exceed_the_remaining_disk_budget(self):
        target = self.parent/"byte-budget"
        with patch("PIL.Image.Image.save", side_effect=lambda writer, **_: writer.write(b"x"*(2*MIB))):
            with self.assertRaisesRegex(ProtocolError, "byte_quota"):
                prepare_browser(self.source, target, max_bytes=MIB)
        self.assertLessEqual(sum(path.stat().st_size for path in target.rglob("*") if path.is_file()), MIB)
        self.assertFalse((target/"COMPLETE").exists())
