"""Local packaging cannot borrow hosted identities, partial runs or another image."""
import copy
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import install_reviewed_backend as installer
from scripts.pilot import local_backend_artifact as local
from scripts.pilot.package_local_backend import build_spec
from scripts.pilot.reviewed_backend_artifact import admit

SOURCE = "a" * 40
IMAGE = "sha256:" + "b" * 64
RUN = "20261016T000001Z-1234abcd"


class LocalRunAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.private = self.root / ".local-pilot"
        self.directory = self.private / f"local-ci/runs/{RUN}"
        self.directory.mkdir(parents=True)
        self.patch = patch.object(local, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.data = {"schemaVersion": 1, "runId": RUN, "state": "success",
            "workflowMode": "maintainer-local-executor", "publicForkJobsAccepted": False,
            "source": {"sha": SOURCE, "repository": "RootOne1337/sphere-platform"},
            "profiles": {"backend": {"state": "success", "isolatedServicesRemoved": True,
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "tests": {"tests": 1, "failures": 0, "errors": 0, "skipped": 0},
                "steps": [{"name": name, "exitCode": 0, "timedOut": False} for name in
                    ["dependencies", "action-contract", "rls-policy", "fresh-migrations", "pytest-real-services", "http-api-documentation"]],
                "github": {"id": 42, "context": "Sphere Local / Backend regressions", "state": "success", "readbackVerified": True}}}}
        (self.directory / "backend-junit.xml").write_text('<testsuites><testsuite><testcase name="executed"/></testsuite></testsuites>')

    def binding(self):
        path = self.directory / "receipt.json"
        path.write_text(json.dumps(self.data), encoding="utf-8")
        return {"file": f"local-ci/runs/{RUN}/receipt.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def status(self):
        return json.dumps([{"context": "Sphere Local / Backend regressions", "id": 42, "state": "success"}])

    def test_exact_complete_suite_junit_and_latest_github_result_are_required(self):
        with patch.object(local, "command", return_value=self.status()):
            self.assertEqual(local.check_local_run(self.binding(), SOURCE), RUN)

    def test_partial_foreign_skipped_or_incomplete_run_is_rejected(self):
        changes = [lambda d: d.update(state="running"), lambda d: d["source"].update(sha="c" * 40),
            lambda d: d["source"].update(repository="foreign/repo"), lambda d: d.update(publicForkJobsAccepted=True),
            lambda d: d["profiles"]["backend"].update(state="error"),
            lambda d: d["profiles"]["backend"].update(isolatedServicesRemoved=False),
            lambda d: d["profiles"]["backend"]["tests"].update(failures=1),
            lambda d: d["profiles"]["backend"]["tests"].update(failures=False),
            lambda d: d["profiles"]["backend"]["tests"].update(skipped=1),
            lambda d: d["profiles"]["backend"]["tests"].update(tests=2),
            lambda d: d["profiles"]["backend"]["steps"].pop(),
            lambda d: d["profiles"]["backend"]["steps"][0].update(exitCode=False),
            lambda d: d["profiles"]["backend"]["steps"][0].update(timedOut=True)]
        original = copy.deepcopy(self.data)
        for change in changes:
            self.data = copy.deepcopy(original)
            change(self.data)
            with self.subTest(change=change), patch.object(local, "command") as command:
                with self.assertRaises(ValueError):
                    local.check_local_run(self.binding(), SOURCE)
                command.assert_not_called()

    def test_modified_junit_cannot_borrow_a_successful_receipt(self):
        (self.directory / "backend-junit.xml").write_text('<testsuites><testcase><failure/></testcase></testsuites>')
        with self.assertRaises(ValueError):
            local.check_local_run(self.binding(), SOURCE)

    def test_later_github_failure_or_wrong_status_id_is_rejected(self):
        binding = self.binding()
        for status in ([], [{"context": "Sphere Local / Backend regressions", "id": 43, "state": "success"}],
                       [{"context": "Sphere Local / Backend regressions", "id": 42, "state": "failure"}]):
            with patch.object(local, "command", return_value=json.dumps(status)), self.assertRaises(ValueError):
                local.check_local_run(binding, SOURCE)

    def test_private_evidence_path_hash_and_budget_are_checked(self):
        binding = self.binding()
        for name in ("../outside", "C:/outside", "/outside", "local-ci\\receipt.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                local.private_file(name)
        with self.assertRaises(ValueError):
            local.hashed_evidence(binding | {"sha256": "0" * 64})
        with self.assertRaises(ValueError):
            local.hashed_evidence(binding | {"runId": "borrowed"})

    def test_local_receipt_is_not_accepted_as_hosted_artifact(self):
        (self.directory / "receipt.json").write_text(json.dumps({"schemaVersion": 1, "kind": "sphere-local-backend"}))
        with self.assertRaises(ValueError):
            admit(self.directory, SOURCE)

    def test_local_admission_binds_real_image_contract_source_and_packaged_probes(self):
        folder = self.private / "local-package"
        folder.mkdir()
        expected = {"backend/requirements.txt": "c" * 64, "backend/schemas/action_contract.v1.json": "d" * 64}
        parent_id = "sha256:" + "e" * 64
        parent_layers = ["sha256:" + "f" * 64]
        config = {"Id": IMAGE, "Os": "linux", "Architecture": "amd64",
            "RootFS": {"Layers": [*parent_layers, "sha256:" + "1" * 64]}, "Config": {
            "User": "sphere", "Cmd": local.COMMAND, "WorkingDir": "/app",
            "Entrypoint": ["/bin/sh", "/app/backend/docker-entrypoint.sh"],
            "Env": ["SPHERE_BUILD_SHA=" + SOURCE], "Labels": {
                "org.opencontainers.image.revision": SOURCE, "io.sphere.local.run": RUN,
                "io.sphere.ci.run": "", "io.sphere.ci.attempt": ""}}}
        runtime = {"image_id": IMAGE, "exit_code": 0, "containers_removed": True,
            "action_contract_verified": True, "network_internal": True, "host_ports": [],
            "source_mount": False, "api_listener": False, "environment": "development"}
        metrics = {"image_id": IMAGE, "passed": True, "container_removed": True,
            "host_ports": [], "network": "none", "backend_source_mount": False, "pilot_modified": False}

        def write_probe(name, value):
            path = folder / name
            path.write_text(json.dumps(value), encoding="utf-8")
            return {"file": "local-package/" + name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

        receipt = {"schemaVersion": 1, "kind": "sphere-local-backend", "sourceRevision": SOURCE,
            "runtimeInstalled": False, "repository": "RootOne1337/sphere-platform",
            "image": {"tag": "sphere-reviewed-backend:" + SOURCE, "id": IMAGE},
            "localExecution": self.binding(), "runtimeProbe": write_probe("runtime.json", runtime),
            "metricsProbe": write_probe("metrics.json", metrics), "migrationHeads": ["head1"],
            "parentImageId": parent_id, "parentSource": "c" * 40,
            "requirementsSha256": "c" * 64, "actionContractSha256": "d" * 64}
        path = folder / "receipt.json"

        def command(args, **kwargs):
            if args[0] == "gh":
                return self.status()
            if args[:3] == ["docker", "image", "inspect"]:
                if args[-1] == parent_id:
                    return json.dumps([{"Id": parent_id, "RootFS": {"Layers": parent_layers}}])
                return json.dumps([config])
            return "head1 (head)"

        original = copy.deepcopy(config)
        with patch.object(local, "validate_source"), patch.object(local, "source_archive", return_value=b"archive"), \
                patch.object(local, "source_files", return_value=expected), \
                patch.object(local, "verify_image_source") as verify, patch.object(local, "command", side_effect=command):
            path.write_text(json.dumps(receipt))
            admitted = local.admit_local(folder, SOURCE)
            self.assertTrue(admitted["localArtifact"])
            self.assertEqual(admitted["archiveBytes"], 0)
            verify.assert_called_once_with(IMAGE, expected)
            for change in [lambda c: c.update(Id="sha256:" + "e" * 64),
                           lambda c: c["Config"].update(User="root"),
                           lambda c: c["Config"].update(Cmd=["sh"]),
                           lambda c: c["Config"].update(Env=["SPHERE_BUILD_SHA=wrong"]),
                           lambda c: c.update(RootFS={"Layers": ["sha256:" + "2" * 64]}),
                           lambda c: c["Config"]["Labels"].update({"io.sphere.ci.run": "123"}),
                           lambda c: c["Config"]["Labels"].update({"io.sphere.local.run": "other"})]:
                config = copy.deepcopy(original)
                change(config)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    local.admit_local(folder, SOURCE)
            config = original
            for item in [receipt | {"kind": "sphere-reviewed-backend"}, receipt | {"runId": 123},
                         receipt | {"archive": {}}, receipt | {"requirementsSha256": "e" * 64}]:
                path.write_text(json.dumps(item))
                with self.subTest(item=item), self.assertRaises(ValueError):
                    local.admit_local(folder, SOURCE)

    def test_packaged_probes_cannot_borrow_another_image_or_live_claims(self):
        runtime = {"image_id": IMAGE, "exit_code": 0, "containers_removed": True,
            "action_contract_verified": True, "network_internal": True, "host_ports": [],
            "source_mount": False, "api_listener": False, "environment": "development"}
        metrics = {"image_id": IMAGE, "passed": True, "container_removed": True,
            "host_ports": [], "network": "none", "backend_source_mount": False, "pilot_modified": False}
        local.check_packaged_probes(runtime, metrics, IMAGE)
        for changed in [runtime | {"image_id": "other"}, runtime | {"exit_code": False},
                        runtime | {"containers_removed": False}, runtime | {"host_ports": [8000]},
                        runtime | {"source_mount": True}, runtime | {"api_listener": True}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                local.check_packaged_probes(changed, metrics, IMAGE)
        for changed in [metrics | {"image_id": "other"}, metrics | {"passed": False},
                        metrics | {"container_removed": False}, metrics | {"pilot_modified": True}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                local.check_packaged_probes(runtime, changed, IMAGE)


class LocalImageAdmissionTests(unittest.TestCase):
    def archive(self, name="backend/main.py", kind=tarfile.REGTYPE):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.size = 3 if kind == tarfile.REGTYPE else 0
            item.linkname = "outside"
            archive.addfile(item, io.BytesIO(b"abc") if item.isfile() else None)
        return stream.getvalue()

    def test_source_archive_is_canonical_independent_of_windows_eol(self):
        with patch.object(local.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = self.archive()
            self.assertEqual(local.source_files(local.source_archive(SOURCE)),
                             {"backend/main.py": hashlib.sha256(b"abc").hexdigest()})
            self.assertEqual(run.call_args.args[0][:4], ["git", "-c", "core.autocrlf=false", "archive"])

    def test_linked_traversal_absolute_and_windows_stream_paths_are_rejected(self):
        for name, kind in [("../outside", tarfile.REGTYPE), ("/outside", tarfile.REGTYPE),
                           ("backend/main.py:stream", tarfile.REGTYPE), ("backend/link", tarfile.SYMTYPE),
                           ("backend/link", tarfile.LNKTYPE)]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                local.source_files(self.archive(name, kind))

    def test_wrong_source_content_or_unexpected_file_is_rejected(self):
        for actual in ({}, {"backend/main.py": "wrong"}, {"backend/main.py": "ok", "backend/foreign.py": "extra"}):
            with patch.object(local, "image_files", return_value=actual), self.assertRaises(ValueError):
                local.verify_image_source(IMAGE, {"backend/main.py": "ok"})

    def test_image_manifest_probe_cannot_run_api_or_use_host_network(self):
        with patch.object(local, "command", return_value="{}") as command:
            local.image_files(IMAGE)
        args = command.call_args.args[0]
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertEqual(args[-3:-1], ["python", "-c"])

    def test_local_build_clears_hosted_identity_and_binds_its_own_run(self):
        spec = build_spec("parent:image", SOURCE, RUN)
        self.assertIn('io.sphere.local.run="' + RUN + '"', spec)
        self.assertIn('io.sphere.ci.run="" io.sphere.ci.attempt=""', spec)
        self.assertNotIn("RUN ", spec)

    def test_missing_local_image_cannot_fall_back_to_an_archive_import(self):
        with patch.object(installer, "command", return_value="") as command, self.assertRaises(ValueError):
            installer.load_or_reuse_image(Path("unused"), {"imageTag": "local:source", "imageId": IMAGE, "localArtifact": True})
        self.assertFalse(any("load" in c.args[0] for c in command.call_args_list))


if __name__ == "__main__":
    unittest.main()
