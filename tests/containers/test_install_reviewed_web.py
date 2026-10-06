"""Installer planning boundaries; no real Docker, GitHub or device commands."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot import install_reviewed_web as installer  # noqa: E402

SOURCE = "a" * 40
TAG = f"sphere-review-frontend:{SOURCE}"
IMAGE_ID = "sha256:" + "b" * 64


def config():
    return {"name": installer.PROJECT, "services": {
        "review-ui": {"image": "previous:image", "environment": {"API_URL": "http://backend:8000"}},
        "review-gateway": {"ports": [{"published": "3015", "host_ip": "127.0.0.1"}]}},
        "networks": {"review": {"internal": True}}}


class InstallTests(unittest.TestCase):
    def test_accepts_only_the_ui_image_delta(self):
        old = config()
        old["services"]["review-ui"]["build"] = {"context": "old-checkout", "args": {"BUILD_SHA": "old"}}
        new = copy.deepcopy(old)
        new["services"]["review-ui"]["image"] = TAG
        del new["services"]["review-ui"]["build"]
        installer.validate_delta(old, new, TAG)
        self.assertEqual(old["services"]["review-ui"]["image"], "previous:image")

    def test_rejects_environment_service_network_and_port_changes(self):
        changes = [lambda c: c["services"]["review-ui"]["environment"].update(API_URL="http://other"),
                   lambda c: c["services"].update(backend={"image": "other"}),
                   lambda c: c["networks"]["review"].update(internal=False),
                   lambda c: c["services"]["review-ui"].update(build={"context": "old-checkout"}),
                   lambda c: c["services"]["review-gateway"]["ports"][0].update(host_ip="0.0.0.0"),
                   lambda c: c["services"]["review-ui"].update(ports=[{"published": "3000"}])]
        for change in changes:
            with self.subTest(change=change):
                old = config()
                new = copy.deepcopy(old)
                new["services"]["review-ui"]["image"] = TAG
                change(new)
                with self.assertRaises(ValueError):
                    installer.validate_delta(old, new, TAG)

    def test_even_unchanged_public_gateway_cannot_be_admitted(self):
        for ports in ([{"published": "3015", "host_ip": "0.0.0.0"}],
                      [{"published": "9999", "host_ip": "127.0.0.1"}]):
            with self.subTest(ports=ports):
                old = config()
                old["services"]["review-gateway"]["ports"] = ports
                new = copy.deepcopy(old)
                new["services"]["review-ui"]["image"] = TAG
                with self.assertRaises(ValueError):
                    installer.validate_delta(old, new, TAG)

    def test_preserves_every_other_container_identity_epoch_and_state(self):
        before = {installer.UI: {"id": "old"}, "api": {"id": "api", "startedAt": "epoch", "status": "running"}}
        after = copy.deepcopy(before)
        after[installer.UI] = {"id": "new"}
        installer.preserved(before, after)
        for field in ("id", "startedAt", "status"):
            changed = copy.deepcopy(after)
            changed["api"][field] = "different"
            with self.assertRaises(ValueError):
                installer.preserved(before, changed)
        with self.assertRaises(ValueError):
            installer.preserved(before, after | {"new-container": {}})

    def test_github_run_attempt_revision_workflow_and_conclusion_are_independent(self):
        receipt = {"runId": 123, "runAttempt": 1, "sourceRevision": SOURCE}
        run = {"head_sha": SOURCE, "run_attempt": 1, "path": ".github/workflows/ci-frontend.yml",
               "name": "CI — Frontend", "status": "completed", "conclusion": "success"}
        with patch.object(installer, "command", return_value=json.dumps(run)):
            installer.check_ci(receipt)
        for field, value in (("head_sha", "b" * 40), ("run_attempt", 2), ("path", "other.yml"),
                             ("name", "Other"), ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(field=field):
                with patch.object(installer, "command", return_value=json.dumps(run | {field: value})):
                    with self.assertRaises(ValueError):
                        installer.check_ci(receipt)

    def test_warning_volume_prevents_load_up_stop_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / ".local-pilot"
            private.mkdir()
            artifact = private / "artifact"
            artifact.mkdir()
            compose = private / "compose.json"
            compose.write_text("{}")
            env = private / ".env"
            env.write_text("")
            old = config()
            new = copy.deepcopy(old)
            new["services"]["review-ui"]["image"] = TAG
            before = {installer.UI: {"id": "old-ui", "imageId": "old-image", "imageTag": "previous:image"}}
            current = {"Id": "old-ui", "Config": {"Env": ["API_URL=http://backend:8000"], "Labels": {
                "com.docker.compose.project": installer.PROJECT, "com.docker.compose.service": "review-ui",
                "com.docker.compose.project.config_files": str(compose),
                "com.docker.compose.project.environment_file": str(env)}}}
            host = {"system": "Windows", "freeDiskBytes": 30 * 1024**3, "totalRamBytes": 32 * 1024**3,
                    "availableRamBytes": 8 * 1024**3, "committedBytes": 30 * 1024**3, "commitLimitBytes": 60 * 1024**3,
                    "volumeHealthStatus": "Warning", "volumeOperationalStatus": ["Full Repair Needed"]}
            calls = []

            def command(args, **kwargs):
                calls.append(args)
                self.assertEqual(args[:2], ["docker", "compose"])
                self.assertEqual(args[-3:], ["config", "--format", "json"])
                return json.dumps(new if args.count("--file") == 2 else old)

            with patch.object(installer, "ROOT", root), patch.object(installer, "PRIVATE", private), \
                    patch.object(installer, "admit", return_value={"imageTag": TAG, "imageId": IMAGE_ID, "runId": 123, "archiveBytes": 100}), \
                    patch.object(installer, "bounded_json", return_value={}), patch.object(installer, "check_ci"), \
                    patch.object(installer, "collect", return_value=host), patch.object(installer, "snapshot", return_value=before), \
                    patch.object(installer, "inspect", return_value=current), patch.object(installer, "command", side_effect=command), \
                    patch.object(installer, "catalog_hash", return_value="catalog-digest"):
                with self.assertRaisesRegex(ValueError, "Host not admitted"):
                    installer.execute(artifact, SOURCE, IMAGE_ID, apply=True)
            self.assertEqual(len(calls), 2)
            plans = list(private.glob("reviewed-web-install-*/plan.json"))
            self.assertEqual(len(plans), 1)
            self.assertFalse(json.loads(plans[0].read_text())["runtimeInstalled"])
            self.assertEqual(json.loads(plans[0].read_text())["resourceFindings"], ["volume_not_ready"])

    def test_self_reported_image_id_cannot_replace_independent_ci_admission(self):
        with patch.object(installer, "private_path", return_value=Path("unused")), \
                patch.object(installer, "admit", return_value={"imageId": "sha256:" + "c" * 64}), \
                patch.object(installer, "command") as command:
            with self.assertRaisesRegex(ValueError, "independent CI admission"):
                installer.execute(Path("unused"), SOURCE, IMAGE_ID, apply=True)
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
