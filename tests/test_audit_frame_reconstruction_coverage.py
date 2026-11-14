import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.audit_frame_reconstruction_coverage import audit


class FullFrameCoverageTests(unittest.TestCase):
    def test_exact_frames_gap_and_unbracketed_tail_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capture = root / "capture"
            capture.mkdir()
            ticks = (0, 45000, 90000, 180000, 270000, 360000)
            rows = [{"index": i, "relative_ticks_90k": t} for i, t in enumerate(ticks)]
            index = "".join(json.dumps(row) + "\n" for row in rows).encode()
            (capture / "frames.jsonl").write_bytes(index)
            manifest = json.dumps(
                {
                    "frames": len(rows),
                    "files": {"frames.jsonl": {"sha256": hashlib.sha256(index).hexdigest()}},
                }
            ).encode()
            (capture / "manifest.json").write_bytes(manifest)
            geometry = {
                "source_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "cameras": [{"image": f"{i:08d}.png", "ticks_90k": ticks[i]} for i in (0, 2, 4)],
            }
            geo = root / "geometry.json"
            geo.write_text(json.dumps(geometry))
            out = root / "result.json"
            with contextlib.redirect_stdout(io.StringIO()):
                audit(capture, geo, out)
            report = json.loads(out.read_text())
            self.assertEqual(report["registered_exact_source_frames"], 3)
            self.assertEqual(report["not_individually_registered"], 3)
            self.assertEqual(report["unbracketed_frames"], 1)
            self.assertEqual(report["inside_temporal_gap_over_1s"], 1)
            self.assertFalse(report["rows"][4]["temporal_gap_over_1s"])
            self.assertTrue(report["temporal_nearness_does_not_prove_pose"])

    def test_changed_frame_index_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            capture = root / "capture"
            capture.mkdir()
            (capture / "frames.jsonl").write_text("tampered")
            manifest = json.dumps(
                {"frames": 1, "files": {"frames.jsonl": {"sha256": "0" * 64}}}
            ).encode()
            (capture / "manifest.json").write_bytes(manifest)
            geo = root / "geometry.json"
            geo.write_text(
                json.dumps(
                    {"source_manifest_sha256": hashlib.sha256(manifest).hexdigest(), "cameras": []}
                )
            )
            with self.assertRaisesRegex(ValueError, "capture_provenance_mismatch"):
                audit(capture, geo, root / "out.json")
