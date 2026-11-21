"""Recovery transfer must reject tampering, path escapes, and accidental overwrites."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.migration.recovery_bundle import MANIFEST, copy_bundle, safe_child, verify


class RecoveryBundleTests(unittest.TestCase):
    def test_verified_copy_and_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            (source / "payload.dump").write_bytes(b"database fixture\x00\xff")
            destination = base / "package"
            result = copy_bundle(source, destination, allow_same_volume=True)
            self.assertTrue(result["verified"])
            self.assertFalse(result["differentLogicalVolume"])
            self.assertEqual((source / "payload.dump").read_bytes(), (destination / "payload.dump").read_bytes())
            (destination / "payload.dump").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "Integrity failure"):
                verify(destination)

    def test_existing_destination_overlap_and_same_disk_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "a").write_text("a")
            with self.assertRaisesRegex(ValueError, "must not exist"):
                copy_bundle(source, source)
            with self.assertRaisesRegex(ValueError, "overlap"):
                copy_bundle(source, source / "inside", True)
            with self.assertRaisesRegex(ValueError, "same logical volume"):
                copy_bundle(source, source.parent / "package")

    def test_manifest_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("../secret", "/absolute", "C:/secret", "..\\secret"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    safe_child(root, name)
            document = {"schemaVersion": 1, "complete": True, "differentLogicalVolume": False,
                        "files": [{"path": "../secret", "bytes": 1, "sha256": "invalid"}]}
            (root / MANIFEST).write_text(json.dumps(document))
            with self.assertRaises(ValueError):
                verify(root)


if __name__ == "__main__":
    unittest.main()
