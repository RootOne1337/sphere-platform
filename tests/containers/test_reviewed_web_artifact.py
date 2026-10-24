"""Exercise archive/source/runtime boundaries without Docker or network."""
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot.reviewed_web_artifact import EXPANDED_LIMIT, admit  # noqa: E402

SOURCE = "a" * 40


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.config = {
            "os": "linux", "architecture": "amd64", "config": {
                "User": "1001:1001", "Cmd": ["node", "server.js"], "WorkingDir": "/app",
                "Entrypoint": ["docker-entrypoint.sh"],
                "Labels": {"org.opencontainers.image.revision": SOURCE,
                           "io.sphere.ci.run": "123", "io.sphere.ci.attempt": "1"},
            },
        }
        self.receipt = {
            "schemaVersion": 1, "sourceRevision": SOURCE, "repository": "RootOne1337/sphere-platform",
            "runId": 123, "runAttempt": 1, "runtimeInstalled": False,
            "image": {"tag": f"sphere-review-frontend:{SOURCE}", "os": "linux", "architecture": "amd64"},
            "archive": {"file": "image.tar.gz", "maxExpandedBytes": EXPANDED_LIMIT},
            "probe": {"loopbackOnly": True, "readOnlyContainer": True, "clientAssetsVerified": 73,
                      "browserHydrationVerified": False, "backendExecutionVerified": False,
                      "pages": [{"route": "/", "status": 200, "redirect": "next-flight"}]
                      + [{"route": route, "status": 200} for route in
                         ("/login", "/scripts", "/scripts/builder", "/devices", "/monitoring")]},
        }

    def bundle(self, change=None, extra=None):
        payload = json.dumps(self.config).encode()
        image_id = hashlib.sha256(payload).hexdigest()
        self.receipt["image"]["id"] = f"sha256:{image_id}"
        manifest = [{"Config": f"blobs/sha256/{image_id}",
                     "Layers": ["blobs/sha256/layer"], "RepoTags": [self.receipt["image"]["tag"]]}]
        if change:
            change(manifest)
        archive = self.directory / "image.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            entries = [(f"blobs/sha256/{image_id}", payload), ("blobs/sha256/layer", b"fixture-layer"),
                       ("manifest.json", json.dumps(manifest).encode())]
            for name, data in entries:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                bundle.addfile(member, io.BytesIO(data))
            if extra:
                bundle.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isfile() else None)
        self.receipt["archive"].update(bytes=archive.stat().st_size,
                                       sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        self.write_receipt()

    def write_receipt(self):
        (self.directory / "receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_admits_one_exact_oci_layout_docker_save_image(self):
        self.bundle()
        result = admit(self.directory, SOURCE)
        self.assertTrue(result["archiveAdmitted"])
        self.assertFalse(result["runtimeInstalled"])
        self.assertEqual(result["pages"], 6)

    def test_compressed_archive_tamper_is_rejected(self):
        self.bundle()
        archive = self.directory / "image.tar.gz"
        data = bytearray(archive.read_bytes())
        data[-1] ^= 1
        archive.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "SHA256"):
            admit(self.directory, SOURCE)

    def test_receipt_and_runtime_constraints(self):
        mutations = [
            lambda: self.receipt.update(sourceRevision="b" * 40),
            lambda: self.receipt.update(repository="other/repo"),
            lambda: self.receipt.update(runId=True),
            lambda: self.receipt.update(runAttempt=0),
            lambda: self.receipt.update(runtimeInstalled=True),
            lambda: self.receipt["image"].update(architecture="arm64"),
            lambda: self.receipt["image"].update(tag="sphere-review-frontend:latest"),
            lambda: self.receipt["archive"].update(file="../image.tar.gz"),
            lambda: self.receipt["archive"].update(maxExpandedBytes=EXPANDED_LIMIT * 2),
            lambda: self.receipt["archive"].update(bytes=True),
            lambda: self.receipt["probe"].update(loopbackOnly=False),
            lambda: self.receipt["probe"].update(readOnlyContainer=False),
            lambda: self.receipt["probe"].update(browserHydrationVerified=True),
            lambda: self.receipt["probe"].update(backendExecutionVerified=True),
            lambda: self.receipt["probe"].update(clientAssetsVerified=0),
            lambda: self.receipt["probe"]["pages"].pop(),
            lambda: self.receipt["probe"]["pages"][0].update(redirect="fake"),
            lambda: self.receipt["probe"]["pages"][1].update(status=500),
            lambda: self.receipt["probe"]["pages"].append(self.receipt["probe"]["pages"][0]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.setUp()  # Fresh immutable fixture for each independent rejection.
                self.bundle()
                mutation()
                self.write_receipt()
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_real_image_config_must_match_receipt_ci_and_nonroot_entry(self):
        for key, value in (("User", "0"), ("WorkingDir", "/"), ("Cmd", ["sh"]),
                           ("Entrypoint", ["sh", "-c"]), ("Volumes", {"/data": {}}),
                           ("Labels", {"org.opencontainers.image.revision": SOURCE})):
            with self.subTest(key=key):
                self.setUp()
                self.config["config"][key] = value
                self.bundle()
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_missing_layer_and_second_image_and_wrong_config_digest(self):
        changes = [lambda m: m[0].update(Layers=["absent"]),
                   lambda m: m.append(m[0]),
                   lambda m: m[0].update(Config="wrong.json"),
                   lambda m: m[0].update(RepoTags=["other:tag"])]
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.bundle(change=change)
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_traversal_links_and_duplicate_members_rejected_without_extraction(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("blobs\\escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE),
                           ("manifest.json", tarfile.REGTYPE)):
            with self.subTest(name=name):
                self.setUp()
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "outside"
                self.bundle(extra=member)
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)
                self.assertFalse((self.directory.parent / "escape").exists())

    def test_rejects_short_sha_before_reading_any_archive(self):
        with self.assertRaisesRegex(ValueError, "full source"):
            admit(self.directory, "abc123")

    def test_receipt_byte_budget(self):
        self.bundle()
        (self.directory / "receipt.json").write_bytes(b" " * (256 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "JSON byte budget"):
            admit(self.directory, SOURCE)

    def test_compressed_byte_budget(self):
        self.bundle()
        with patch("scripts.pilot.reviewed_web_artifact.COMPRESSED_LIMIT", 1):
            with self.assertRaisesRegex(ValueError, "Compressed image size"):
                admit(self.directory, SOURCE)

    def test_expanded_tar_budget_does_not_require_extracting_a_large_payload(self):
        self.bundle()
        self.receipt["archive"]["maxExpandedBytes"] = 100
        self.write_receipt()
        with patch("scripts.pilot.reviewed_web_artifact.EXPANDED_LIMIT", 100):
            with self.assertRaisesRegex(ValueError, "Expanded image budget"):
                admit(self.directory, SOURCE)

    def test_receipt_image_digest_cannot_replace_actual_config_hash(self):
        self.bundle()
        self.receipt["image"]["id"] = "sha256:" + "b" * 64
        self.write_receipt()
        with self.assertRaisesRegex(ValueError, "config digest"):
            admit(self.directory, SOURCE)


if __name__ == "__main__":
    unittest.main()
