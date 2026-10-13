import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import reviewed_artifact_retention as retention


class ReviewedCacheRetentionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.directory = self.base / "reviewed-backend-1234567"
        self.directory.mkdir()
        self.archive = self.directory / "image.tar.gz"
        self.archive.write_bytes(b"cached-image")
        self.receipt = {
            "sourceRevision": "a" * 40,
            "archive": {"bytes": 12, "sha256": hashlib.sha256(b"cached-image").hexdigest()},
        }

    def test_only_verified_named_archive_is_removed_and_receipts_survive(self):
        marker = self.directory / "receipt.json"
        marker.write_text(json.dumps(self.receipt))
        unrelated = self.directory / "personal.txt"
        unrelated.write_text("preserve")
        item = retention.archive_identity(self.directory, self.receipt, "image.tar.gz", self.base)
        retention.remove_archive(self.base, item)
        self.assertFalse(self.archive.exists())
        self.assertTrue(marker.exists())
        self.assertEqual(unrelated.read_text(), "preserve")

    def test_changed_content_before_removal_is_retained(self):
        item = retention.archive_identity(self.directory, self.receipt, "image.tar.gz", self.base)
        self.archive.write_bytes(b"changed-data")
        with self.assertRaisesRegex(ValueError, "changed_before"):
            retention.remove_archive(self.base, item)
        self.assertTrue(self.archive.exists())

    def test_invalid_hash_or_filename_cannot_authorize_cleanup(self):
        for name, receipt in [
            ("other.tar.gz", self.receipt),
            ("image.tar.gz", {"archive": {"bytes": 12, "sha256": "f" * 64}}),
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                retention.archive_identity(self.directory, receipt, name, self.base)
        self.assertTrue(self.archive.exists())

    def test_zip_needs_matching_authenticated_download_proof(self):
        zip_file = self.directory / "download.zip"
        zip_file.write_bytes(b"download")
        proof = {
            "githubDigestVerified": False,
            "sourceRevision": "a" * 40,
            "zipBytes": 8,
            "zipSha256": hashlib.sha256(b"download").hexdigest(),
        }
        file = self.directory / "download-proof.json"
        file.write_text(json.dumps(proof))
        with self.assertRaises(ValueError):
            retention.archive_identity(self.directory, self.receipt, "download.zip", self.base)
        proof["githubDigestVerified"] = True
        file.write_text(json.dumps(proof))
        self.assertEqual(
            retention.archive_identity(self.directory, self.receipt, "download.zip", self.base)[
                "bytes"
            ],
            8,
        )
        proof["sourceRevision"] = "b" * 40
        file.write_text(json.dumps(proof))
        with self.assertRaises(ValueError):
            retention.archive_identity(self.directory, self.receipt, "download.zip", self.base)

    def test_absolute_outside_path_is_never_removed(self):
        with tempfile.TemporaryDirectory() as outside:
            file = Path(outside) / "preserve.tar.gz"
            file.write_bytes(b"cached-image")
            with self.assertRaises(ValueError):
                retention.remove_archive(
                    self.base,
                    {"file": str(file), "bytes": 12, "sha256": self.receipt["archive"]["sha256"]},
                )
            self.assertTrue(file.exists())

    def test_keep_distinct_sources_per_component(self):
        records = [
            {"kind": kind, "source": str(i), "created": str(i)}
            for kind in retention.NAMES
            for i in range(5)
        ]
        records.append({"kind": retention.NAMES[0], "source": "4", "created": "9"})
        self.assertEqual(retention.retained_sources(records, 3), {"2", "3", "4"})

    def test_failed_maintenance_is_visible_and_does_not_raise_into_runtime_rollback(self):
        with patch.object(retention, "execute", side_effect=RuntimeError("busy")):
            result = retention.post_install(self.base, "a" * 40, "sha256:" + "b" * 64)
        self.assertEqual(result["state"], "not-completed")
        self.assertFalse(result["cleanupClaimed"])

    def test_previous_runtime_is_protected_even_for_a_downgrade(self):
        with patch.object(
            retention,
            "execute",
            return_value={
                "receiptFile": "receipt.json",
                "removedArchives": [],
                "removedImages": [],
            },
        ) as execute:
            result = retention.post_install(self.base, "a" * 40, "sha256:" + "b" * 64)
        self.assertEqual(execute.call_args.kwargs["protect_images"], ("sha256:" + "b" * 64,))
        self.assertEqual(result["state"], "completed")


if __name__ == "__main__":
    unittest.main()
