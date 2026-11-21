import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.compare_sfm_overlap import compare


class CompareSfMOverlapTests(unittest.TestCase):
    def test_similarity_alignment_and_heldout_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cameras = []
            alternate = []
            for index, seconds in enumerate(
                (25.0, 25.5, 26.0, 26.5, 27.0, 27.5, 28.0, 29.0, 30.0, 31.0, 32.0)
            ):
                # Non-collinear points with a known orientation-preserving
                # similarity transformation and shifted later held-out views.
                x, y, z = index, index**2 * 0.1, index * 0.3
                cameras.append(
                    {
                        "image": f"{index}.png",
                        "ticks_90k": int(seconds * 90000),
                        "center": [x, y, z],
                    }
                )
                shifted = 2 if seconds >= 29 else 0
                alternate.append(
                    {
                        "image": f"{index}.png",
                        "ticks_90k": int(seconds * 90000),
                        "center": [-y / 2 + 4, (x + shifted) / 2 + 2, z / 2 - 3],
                    }
                )
            a = root / "a.json"
            b = root / "b.json"
            out = root / "out.json"
            a.write_text(json.dumps({"source_manifest_sha256": "a", "cameras": cameras}))
            b.write_text(json.dumps({"source_manifest_sha256": "a", "cameras": alternate}))
            with contextlib.redirect_stdout(io.StringIO()):
                compare(a, b, out)
            report = json.loads(out.read_text())
            self.assertEqual(report["fit"]["count"], 7)
            self.assertEqual(report["heldout"]["count"], 4)
            self.assertLess(report["fit"]["maximum"], 1e-9)
            self.assertGreater(report["heldout"]["median"], 1.0)
            self.assertTrue(report["disagreement_is_not_error"])

    def test_rejects_different_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = root / "a"
            b = root / "b"
            a.write_text(json.dumps({"source_manifest_sha256": "a", "cameras": []}))
            b.write_text(json.dumps({"source_manifest_sha256": "b", "cameras": []}))
            with self.assertRaisesRegex(ValueError, "comparison_source_mismatch"):
                compare(a, b, root / "out")
