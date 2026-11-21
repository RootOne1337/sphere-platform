import json
import sqlite3
import tempfile
import unittest
import zipfile
from contextlib import closing
from pathlib import Path

from scripts.migration.backup_codex import capture, snapshot_sqlite, verify


class CodexBackupTests(unittest.TestCase):
    def test_committed_wal_is_present_in_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "live.sqlite"
            with closing(sqlite3.connect(source)) as writer:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("CREATE TABLE chats(id TEXT)")
                writer.execute("INSERT INTO chats VALUES ('preserved')")
                writer.commit()
                result = snapshot_sqlite(source, root / "copy.sqlite")
                self.assertEqual(result["integrityCheck"], "ok")
                with closing(sqlite3.connect(root / "copy.sqlite")) as copied:
                    self.assertEqual(copied.execute("SELECT id FROM chats").fetchone(), ("preserved",))
                with self.assertRaises(ValueError):
                    snapshot_sqlite(source, root / "copy.sqlite")

    def test_archive_hash_verification_rejects_changed_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with zipfile.ZipFile(root / "codex-private.zip", "w") as archive:
                archive.writestr("codex-home/config.toml", "fixture")
            (root / "manifest.json").write_text(json.dumps({"files": [
                {"path": "codex-home/config.toml", "bytes": 7, "sha256": "tampered"}
            ], "sqlite": []}))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify(root)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ValueError):
                capture(Path(temporary), Path(temporary))


if __name__ == "__main__":
    unittest.main()
