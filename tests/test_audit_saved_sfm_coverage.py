import contextlib
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.audit_saved_sfm_coverage import audit


class CoverageAuditTests(unittest.TestCase):
    def test_selected_missing_view_has_verified_nearby_edge(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "job"
            prepared = root / "prepared"
            prepared.mkdir(parents=True)
            capture = Path(folder) / "capture"
            capture.mkdir()
            frames = [
                {"index": 0, "relative_ticks_90k": 0},
                {"index": 1, "relative_ticks_90k": 45000},
            ]
            frame_bytes = "".join(json.dumps(x) + "\n" for x in frames).encode()
            (capture / "frames.jsonl").write_bytes(frame_bytes)
            manifest_bytes = json.dumps(
                {
                    "frames": 2,
                    "files": {"frames.jsonl": {"sha256": hashlib.sha256(frame_bytes).hexdigest()}},
                }
            ).encode()
            (capture / "manifest.json").write_bytes(manifest_bytes)
            (root / "geometry.json").write_text(
                json.dumps(
                    {
                        "cameras": [{"image": "00000000.png"}],
                        "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                    }
                )
            )
            with contextlib.closing(sqlite3.connect(prepared / "database.db")) as db, db:
                db.execute("create table images(image_id integer, name text)")
                db.execute("create table keypoints(image_id integer, rows integer)")
                db.execute("create table two_view_geometries(pair_id integer, rows integer)")
                db.executemany(
                    "insert into images values (?, ?)", [(1, "00000000.png"), (2, "00000001.png")]
                )
                db.executemany("insert into keypoints values (?, ?)", [(1, 42), (2, 55)])
                db.execute("insert into two_view_geometries values (?, ?)", (2147483647 + 2, 31))
            out = Path(folder) / "result.json"
            with contextlib.redirect_stdout(io.StringIO()):
                audit(root, capture, out)
            result = json.loads(out.read_text())
            self.assertEqual(
                (result["selected"], result["registered_primary"], result["missing_primary"]),
                (2, 1, 1),
            )
            self.assertEqual(result["missing_with_at_least_24_nearby_inliers"], 1)
            self.assertEqual(result["missing"][0]["nearby_primary_max"], 31)
            self.assertEqual(result["missing"][0]["nearby_strongest_seconds"], 0)
            self.assertTrue(result["pair_edges_do_not_prove_pose_or_explain_failure"])
            (capture / "frames.jsonl").write_bytes(frame_bytes + b" ")
            with self.assertRaisesRegex(ValueError, "capture_provenance_mismatch"):
                audit(root, capture, Path(folder) / "mismatched.json")

    def test_nonempty_wal_is_not_silently_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "job"
            prepared = root / "prepared"
            prepared.mkdir(parents=True)
            (prepared / "database.db").touch()
            (prepared / "database.db-wal").write_bytes(b"live")
            with self.assertRaisesRegex(ValueError, "database_not_immutable"):
                audit(root, Path(folder) / "capture", Path(folder) / "out.json")
