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
    reconstruction_rows,
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
    def test_terminal_frame_replaces_a_crowded_neighbor_without_dropping_the_exact_endpoint(self):
        frames=[dict(index=i,relative_ticks_90k=round(t*90000)) for i,t in enumerate([0,.25,.5,.75,1.,1.031])]
        before=json.loads(json.dumps(frames))
        rows,sampling=reconstruction_rows(frames,.25)
        self.assertEqual([r['index'] for r in rows],[0,1,2,3,5])
        self.assertEqual(sampling['final_close_neighbor_replaced_source_index'],4)
        self.assertEqual(sampling['last_source_index'],5)
        self.assertAlmostEqual(sampling['minimum_interval_seconds'],.25)
        self.assertFalse(sampling['stationary_detection_applied'])
        self.assertEqual(frames,before)

    def test_heldout_endpoints_short_clips_and_a_well_spaced_last_frame_remain_exact(self):
        frames=[dict(index=i,relative_ticks_90k=round(t*90000)) for i,t in enumerate([0,.25,.5,.75,.95])]
        rows,sampling=reconstruction_rows(frames,.25)
        self.assertEqual([r['index'] for r in rows],[0,1,2,3,4])
        self.assertIsNone(sampling['final_close_neighbor_replaced_source_index'])
        rows,_=reconstruction_rows(frames,1.,frozenset({0,4}))
        self.assertEqual([r['index'] for r in rows],[1,3])
        rows,_=reconstruction_rows(frames[:2],1.)
        self.assertEqual([r['index'] for r in rows],[0,1])

    def test_png_preparation_uses_balanced_tail_and_preserves_source_and_provenance(self):
        before={p.name:digest(p.read_bytes()) for p in self.source.iterdir()}
        output=self.parent/'balanced-tail'
        prepare_browser(self.source,output,interval=.23)
        prepared=json.loads((output/'reconstruction-input.json').read_bytes())
        self.assertEqual([r['source_index'] for r in prepared['images']],[0,7,15])
        self.assertEqual(prepared['sampling']['final_close_neighbor_replaced_source_index'],14)
        self.assertEqual(prepared['images'][-1]['relative_ticks_90k'],self.frames[-1]['relative_ticks_90k'])
        self.assertFalse((output/'images/00000014.png').exists())
        self.assertTrue((output/'images/00000015.png').is_file())
        self.assertEqual(before,{p.name:digest(p.read_bytes()) for p in self.source.iterdir()})
    def test_heldout_indices_never_enter_preparation_including_the_last_frame(self):
        before={p.name:digest(p.read_bytes()) for p in self.source.iterdir()}
        output=self.parent/'heldout-prepare'
        prepare_browser(self.source,output,interval=.2,excluded_indices=frozenset({0,6,15}))
        provenance=json.loads((output/'reconstruction-input.json').read_bytes())
        selected={row['source_index'] for row in provenance['images']}
        self.assertFalse(selected & {0,6,15})
        self.assertEqual(provenance['excluded_source_indices'],[0,6,15])
        self.assertIn(14,selected)
        self.assertEqual(before,{p.name:digest(p.read_bytes()) for p in self.source.iterdir()})

    def test_invalid_or_exhaustive_heldout_sets_are_refused_before_output(self):
        for indices in ({0},frozenset({True}),frozenset({99}),frozenset(range(16))):
            with self.subTest(indices=indices),self.assertRaises(ProtocolError):
                prepare_browser(self.source,self.parent/'invalid',excluded_indices=indices)
            self.assertFalse((self.parent/'invalid').exists())

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

    def test_observability_reports_real_media_gaps_without_trusting_claimed_engine_data(self):
        self.manifest["config"].update(target_fps=60, measured_depth=True, camera_poses=[1, 2, 3])
        for i, row in enumerate(self.frames):
            ticks = i*3000+(45000 if i >= 8 else 0)
            row.update(relative_ticks_90k=ticks, rtp_timestamp=(2**32-3000+ticks) % 2**32)
        self.manifest["media_duration_ticks_90k"] = self.frames[-1]["relative_ticks_90k"]
        self.seal()
        before = {p.name: digest(p.read_bytes()) for p in self.source.iterdir()}
        report = inspect_browser(self.source)
        quality = report["observability"]
        self.assertEqual(quality["declared_target_fps"], 60)
        self.assertAlmostEqual(report["media_fps"], 15)
        self.assertAlmostEqual(quality["media_spacing"]["median_ms"], 1000/30)
        self.assertAlmostEqual(quality["media_spacing"]["p95_ms"], 1600/3)
        self.assertEqual(quality["media_spacing"]["gaps_over_500ms"], 1)
        self.assertIsNone(quality["capture_to_receive_latency_ms"])
        self.assertIsNone(quality["metric_scale"])
        self.assertFalse(quality["measured_depth"])
        self.assertFalse(quality["engine_camera_poses"])
        self.assertFalse(quality["calibrated_intrinsics"])
        self.assertEqual(before, {p.name: digest(p.read_bytes()) for p in self.source.iterdir()})

    def test_single_frame_has_no_fabricated_spacing_or_latency(self):
        self.frames = self.frames[:1]
        path = self.source/"video.h264"
        path.write_bytes(path.read_bytes()[:self.frames[0]["bytes"]])
        self.manifest.update(frames=1, media_duration_ticks_90k=0)
        self.manifest["config"]["target_fps"] = True
        self.seal()
        report = inspect_browser(self.source)
        quality = report["observability"]
        self.assertIsNone(quality["declared_target_fps"])
        self.assertEqual(quality["unique_decoded_rgb"], 1)
        self.assertEqual(quality["consecutive_identical_rgb"], 0)
        self.assertEqual(quality["media_spacing"]["intervals"], 0)
        self.assertIsNone(quality["media_spacing"]["p95_ms"])
        self.assertIsNone(quality["media_spacing"]["max_ms"])
        self.assertEqual(report["media_fps"], 0)

    def test_static_rgb_is_reported_without_fabricating_a_game_disconnect(self):
        codec = av.CodecContext.create("libx264", "w")
        codec.width, codec.height, codec.pix_fmt = 96, 64, "yuv420p"
        codec.time_base = Fraction(1, 30)
        codec.options = {"preset": "ultrafast", "tune": "zerolatency", "crf": "0"}
        packets = []
        for i in range(16):
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 96, 3), dtype=np.uint8), format="rgb24")
            frame.pts = i
            packets.extend(codec.encode(frame))
        packets.extend(codec.encode(None))
        video = bytearray()
        self.assertEqual(len(packets), len(self.frames))
        for row, packet in zip(self.frames, packets):
            data = bytes(packet)
            types = set(nal_types(data))
            row.update(offset=len(video), bytes=len(data), key=5 in types,
                       seekable={5, 7, 8}.issubset(types), sha256=digest(data))
            video.extend(data)
        (self.source/"video.h264").write_bytes(video)
        self.seal()
        report = inspect_browser(self.source)
        self.assertEqual(report["observability"]["unique_decoded_rgb"], 1)
        self.assertEqual(report["observability"]["consecutive_identical_rgb"], 15)
        self.assertTrue(report["observability"]["exact_rgb_repeats_are_not_a_disconnect_verdict"])
        self.assertFalse(report["execution_qualified"])

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
