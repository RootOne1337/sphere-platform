"""Exercise API artifact admission and bounded packaging without Docker/network."""
import gzip
import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot.reviewed_backend_artifact import COMMAND, EXPANDED_LIMIT, admit  # noqa: E402

spec = importlib.util.spec_from_file_location("packaged_backend", Path(__file__).with_name("package_reviewed_backend.py"))
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)
SOURCE = "a" * 40


class BackendAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.directory = Path(temporary.name)
        self.addCleanup(temporary.cleanup)
        self.config = {"os": "linux", "architecture": "amd64", "config": {
            "User": "sphere", "Cmd": COMMAND, "WorkingDir": "/app",
            "Entrypoint": ["/bin/sh", "/app/backend/docker-entrypoint.sh"],
            "Env": [f"SPHERE_BUILD_SHA={SOURCE}", "PYTHONPATH=/app"],
            "Labels": {"org.opencontainers.image.revision": SOURCE, "io.sphere.ci.run": "123", "io.sphere.ci.attempt": "1"},
        }}
        self.receipt = {"schemaVersion": 1, "kind": "sphere-reviewed-backend", "sourceRevision": SOURCE,
            "repository": "RootOne1337/sphere-platform", "runId": 123, "runAttempt": 1, "runtimeInstalled": False,
            "image": {"tag": f"sphere-reviewed-backend:{SOURCE}", "os": "linux", "architecture": "amd64"},
            "archive": {"file": "image.tar.gz", "maxExpandedBytes": EXPANDED_LIMIT},
            "requirementsSha256": "b" * 64, "actionContractSha256": "c" * 64, "migrationHeads": ["2026_01_head"],
            "probe": {"isolatedRuntimeVerified": True, "actionContractVerified": True, "actionContractVersion": "1.0",
                "multiprocessMetricsVerified": True, "throwawayContainersRemoved": True, "readOnlyApplication": True,
                "hostPorts": [], "environment": "development", "productionRoleRolloutVerified": False,
                "androidExecutionVerified": False, "liveApiVerified": False}}

    def bundle(self, change=None, extra=None):
        payload = json.dumps(self.config).encode()
        digest = hashlib.sha256(payload).hexdigest()
        self.receipt["image"]["id"] = "sha256:" + digest
        manifest = [{"Config": f"blobs/sha256/{digest}", "Layers": ["blobs/sha256/layer"],
                     "RepoTags": [self.receipt["image"]["tag"]]}]
        if change:
            change(manifest)
        archive = self.directory / "image.tar.gz"
        with tarfile.open(archive, "w:gz") as stream:
            for name, data in [(f"blobs/sha256/{digest}", payload), ("blobs/sha256/layer", b"fixture-layer"),
                               ("manifest.json", json.dumps(manifest).encode())]:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                stream.addfile(member, io.BytesIO(data))
            if extra:
                stream.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isfile() else None)
        self.receipt["archive"].update(bytes=archive.stat().st_size,
                                      sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        self.write_receipt()

    def write_receipt(self):
        (self.directory / "receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_admits_exact_packaged_backend_without_claiming_runtime_install(self):
        self.bundle()
        receipt = admit(self.directory, SOURCE)
        self.assertTrue(receipt["archiveAdmitted"])
        self.assertFalse(receipt["runtimeInstalled"])
        self.assertEqual(receipt["migrationHeads"], ["2026_01_head"])

    def test_identity_contract_and_unproven_live_claims_are_rejected(self):
        changes = [
            lambda r: r.update(kind="sphere-reviewed-web"), lambda r: r.update(sourceRevision="b" * 40),
            lambda r: r.update(repository="other/repository"), lambda r: r.update(runId=True),
            lambda r: r.update(runAttempt=0), lambda r: r.update(runtimeInstalled=True),
            lambda r: r["image"].update(tag="sphere-reviewed-backend:latest"),
            lambda r: r["image"].update(architecture="arm64"),
            lambda r: r["probe"].update(actionContractVersion="2.0"),
            lambda r: r["probe"].update(hostPorts=[8000]),
            lambda r: r["probe"].update(environment="production"),
            lambda r: r.update(migrationHeads=[]), lambda r: r.update(migrationHeads=["one", "two"]),
            lambda r: r.update(requirementsSha256="unknown"), lambda r: r.update(actionContractSha256=None),
        ]
        for flag in ("productionRoleRolloutVerified", "androidExecutionVerified", "liveApiVerified"):
            changes.append(lambda r, key=flag: r["probe"].update({key: True}))
        for flag in ("isolatedRuntimeVerified", "actionContractVerified", "multiprocessMetricsVerified",
                     "throwawayContainersRemoved", "readOnlyApplication"):
            changes.append(lambda r, key=flag: r["probe"].update({key: False}))
        for change in changes:
            with self.subTest(change=change):
                self.setUp()
                self.bundle()
                change(self.receipt)
                self.write_receipt()
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_runtime_user_entry_and_build_identity_are_bound_to_actual_config(self):
        changes = [("User", "root"), ("Cmd", ["sh"]), ("Entrypoint", ["/bin/sh"]), ("WorkingDir", "/"),
                   ("Volumes", {"/app": {}}), ("Labels", {}), ("Env", ["SPHERE_BUILD_SHA=unknown"]),
                   ("Env", [f"SPHERE_BUILD_SHA={SOURCE}", f"SPHERE_BUILD_SHA={SOURCE}"])]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                self.setUp()
                self.config["config"][field] = value
                self.bundle()
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_second_image_wrong_tag_missing_or_directory_layer_are_rejected(self):
        for change in [lambda m: m.append(m[0]), lambda m: m[0].update(RepoTags=["wrong:tag"]),
                       lambda m: m[0].update(Config="absent"), lambda m: m[0].update(Layers=["absent"])]:
            with self.subTest(change=change):
                self.setUp()
                self.bundle(change)
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)
        self.setUp()
        directory = tarfile.TarInfo("directory-layer")
        directory.type = tarfile.DIRTYPE
        self.bundle(lambda m: m[0].update(Layers=["directory-layer"]), extra=directory)
        with self.assertRaisesRegex(ValueError, "Missing image layers"):
            admit(self.directory, SOURCE)

    def test_mismatched_hashes_and_archive_names_are_rejected(self):
        for change in [lambda r: r["image"].update(id="sha256:" + "d" * 64),
                       lambda r: r["archive"].update(sha256="e" * 64),
                       lambda r: r["archive"].update(file="../image.tar.gz"),
                       lambda r: r["archive"].update(bytes=True)]:
            with self.subTest(change=change):
                self.setUp()
                self.bundle()
                change(self.receipt)
                self.write_receipt()
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_traversal_links_and_duplicates_are_rejected_without_extraction(self):
        for name, kind in [("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("a\\escape", tarfile.REGTYPE), ("linked", tarfile.SYMTYPE),
                           ("manifest.json", tarfile.REGTYPE)]:
            with self.subTest(name=name):
                self.setUp()
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "outside"
                self.bundle(extra=member)
                with self.assertRaises(ValueError):
                    admit(self.directory, SOURCE)

    def test_budgets_and_short_source_fail_before_docker(self):
        self.bundle()
        with self.assertRaises(ValueError):
            admit(self.directory, "abc")
        with patch("scripts.pilot.reviewed_backend_artifact.COMPRESSED_LIMIT", 1):
            with self.assertRaisesRegex(ValueError, "Compressed image size"):
                admit(self.directory, SOURCE)
        self.receipt["archive"]["maxExpandedBytes"] = 100
        self.write_receipt()
        with patch("scripts.pilot.reviewed_backend_artifact.EXPANDED_LIMIT", 100):
            with self.assertRaisesRegex(ValueError, "Expanded image budget"):
                admit(self.directory, SOURCE)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.path = Path(temporary.name) / "image.tar.gz"
        self.addCleanup(temporary.cleanup)
        self.process = Mock(stdout=io.BytesIO(b"docker-save-fixture" * 100))
        self.process.wait.return_value = 0
        self.process.poll.return_value = None

    def test_streamed_gzip_is_original_bytes_and_no_uncompressed_copy_exists(self):
        with patch.object(packaging.subprocess, "Popen", return_value=self.process):
            receipt = packaging.save_archive("owned-image", self.path)
        self.assertEqual(gzip.decompress(self.path.read_bytes()), b"docker-save-fixture" * 100)
        self.assertEqual(receipt["sha256"], hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_failed_docker_save_removes_only_owned_partial_and_hides_native_output(self):
        self.process.wait.return_value = 1
        with patch.object(packaging.subprocess, "Popen", return_value=self.process):
            with self.assertRaisesRegex(ValueError, "Image save failed"):
                packaging.save_archive("owned-image", self.path)
        self.assertFalse(self.path.exists())

    def test_existing_file_is_not_deleted_on_exclusive_open_failure(self):
        self.path.write_bytes(b"existing-artifact")
        with patch.object(packaging.subprocess, "Popen", return_value=self.process):
            with self.assertRaises(FileExistsError):
                packaging.save_archive("owned-image", self.path)
        self.assertEqual(self.path.read_bytes(), b"existing-artifact")

    def test_uncompressed_and_compressed_budgets_kill_save_and_remove_partial(self):
        for limit in ["EXPANDED_LIMIT", "COMPRESSED_LIMIT"]:
            with self.subTest(limit=limit):
                self.setUp()
                with patch.object(packaging.subprocess, "Popen", return_value=self.process), patch.object(packaging, limit, 1):
                    with self.assertRaisesRegex(ValueError, "budget exceeded"):
                        packaging.save_archive("owned-image", self.path)
                self.process.kill.assert_called_once()
                self.assertFalse(self.path.exists())

    def test_packaging_refuses_local_host_before_commands_or_writes(self):
        with patch.dict(packaging.os.environ, {"GITHUB_ACTIONS": "false"}), patch.object(packaging, "command") as command:
            with self.assertRaisesRegex(ValueError, "Hosted Linux CI"):
                packaging.package()
        command.assert_not_called()

    def test_probe_receipts_require_same_image_real_success_and_cleanup(self):
        runtime = {"image_id": "image", "exit_code": 0, "containers_removed": True, "action_contract_verified": True,
            "network_internal": True, "host_ports": [], "source_mount": False, "api_listener": False, "environment": "development"}
        metrics = {"image_id": "image", "passed": True, "container_removed": True, "host_ports": [],
            "network": "none", "backend_source_mount": False, "pilot_modified": False}
        packaging.check_probes(runtime, metrics, "image")
        for target, field, value in [(runtime, "image_id", "other"), (runtime, "exit_code", False),
            (runtime, "exit_code", 1), (runtime, "action_contract_verified", False), (runtime, "containers_removed", False),
            (runtime, "host_ports", [8000]), (runtime, "source_mount", True), (metrics, "passed", False),
            (metrics, "container_removed", False), (metrics, "image_id", "other"), (metrics, "pilot_modified", True)]:
            with self.subTest(field=field, value=value):
                old = target[field]
                target[field] = value
                with self.assertRaises(ValueError):
                    packaging.check_probes(runtime, metrics, "image")
                target[field] = old


if __name__ == "__main__":
    unittest.main()
