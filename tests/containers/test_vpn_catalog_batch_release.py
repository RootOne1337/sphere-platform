import hashlib
import subprocess
import unittest
from unittest.mock import patch

from scripts.pilot import vpn_catalog_batch_release as release


class CatalogBatchBoundaryTests(unittest.TestCase):
    def test_only_frozen_eight_files_and_same_schema_are_admitted(self):
        content = b"reviewed source\n"
        digest = hashlib.sha256(content).hexdigest()
        files = {path: digest for path in release.FILES}
        receipt = {"migrationHeads": [release.HEAD], "requirementsSha256": digest, "actionContractSha256": digest}
        with patch.object(release, "FILES", files), patch.object(release, "command", return_value="\n".join(files)), \
                patch.object(release.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, content, b"")):
            self.assertEqual(set(release.source_boundary(release.BASELINE, "a" * 40, receipt)), set(files))

    def test_wrong_baseline_or_new_schema_is_rejected_before_git(self):
        for baseline, head in [("b" * 40, release.HEAD), (release.BASELINE, "future_head")]:
            with self.subTest(baseline=baseline), patch.object(release, "command") as command:
                with self.assertRaises(ValueError):
                    release.source_boundary(baseline, "a" * 40, {"migrationHeads": [head]})
                command.assert_not_called()

    def test_unreviewed_file_and_source_fingerprint_are_rejected(self):
        receipt = {"migrationHeads": [release.HEAD]}
        with patch.object(release, "command", return_value="\n".join([*release.FILES, "alembic/unsafe.py"])):
            with self.assertRaises(ValueError):
                release.source_boundary(release.BASELINE, "a" * 40, receipt)
        with patch.object(release, "command", return_value="\n".join(release.FILES)), \
                patch.object(release.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"changed", b"")):
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                release.source_boundary(release.BASELINE, "a" * 40, receipt)
