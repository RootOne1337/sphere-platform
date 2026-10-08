"""Operational backend update boundaries, without live Docker/API mutations."""
import copy
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot import install_reviewed_backend as installer  # noqa: E402

SOURCE = "a" * 40
CURRENT = "c" * 40
IMAGE = "sha256:" + "b" * 64
TAG = f"sphere-reviewed-backend:{SOURCE}"


def configuration():
    return {"name": installer.PROJECT, "services": {
        "backend": {"image": "previous:image", "build": {"context": "."},
                    "environment": {"POSTGRES_URL": "postgresql://postgres/example"},
                    "volumes": [{"target": "/app/agent-config", "read_only": True, "type": "bind"},
                                {"target": "/app/backend/updates", "type": "volume"},
                                {"target": "/var/lib/sphere/device-logs", "type": "volume"},
                                {"target": "/var/lib/sphere/updates", "type": "bind"}]},
        "postgres": {"image": "unchanged:postgres"}}, "networks": {"default": {"internal": True}}}


def candidate(old):
    new = copy.deepcopy(old)
    new["services"]["backend"]["image"] = TAG
    del new["services"]["backend"]["build"]
    return new


class BackendInstallerTests(unittest.TestCase):
    def test_only_backend_image_and_build_recipe_can_change(self):
        old = configuration()
        installer.validate_delta(old, candidate(old), TAG)
        changes = [lambda c: c["services"]["backend"]["environment"].update(POSTGRES_URL="other"),
                   lambda c: c["services"]["postgres"].update(image="changed"),
                   lambda c: c["networks"]["default"].update(internal=False),
                   lambda c: c["services"]["backend"]["volumes"][0].update(source="other"),
                   lambda c: c["services"]["backend"].update(build={"context": "."})]
        for change in changes:
            with self.subTest(change=change):
                new = candidate(old)
                change(new)
                with self.assertRaises(ValueError):
                    installer.validate_delta(old, new, TAG)

    def test_unchanged_source_mount_runtime_override_and_public_port_are_rejected(self):
        changes = [lambda c: c.update(ports=[{"published": "8000"}]),
                   lambda c: c.update(user="root"), lambda c: c.update(command=["python", "other.py"]),
                   lambda c: c.update(entrypoint=["/bin/sh", "other.sh"]),
                   lambda c: c["environment"].update(SPHERE_BUILD_SHA=SOURCE),
                   lambda c: c["volumes"].append({"target": "/app/backend", "type": "bind"}),
                   lambda c: c["volumes"][0].update(read_only=False),
                   lambda c: c.update(volumes=[])]
        for change in changes:
            with self.subTest(change=change):
                old = configuration()
                change(old["services"]["backend"])
                with self.assertRaises(ValueError):
                    installer.validate_delta(old, candidate(old), TAG)

    def test_every_other_container_epoch_identity_and_status_are_fenced(self):
        before = {installer.BACKEND: {"id": "api"}, "postgres": {
            "id": "pg", "startedAt": "epoch", "status": "running", "imageId": "pg-image"}}
        after = copy.deepcopy(before)
        after[installer.BACKEND] = {"id": "new-api"}
        installer.preserved(before, after)
        for key in before["postgres"]:
            changed = copy.deepcopy(after)
            changed["postgres"][key] = "changed"
            with self.subTest(key=key), self.assertRaises(ValueError):
                installer.preserved(before, changed)
        with self.assertRaises(ValueError):
            installer.preserved(before, after | {"another": {}})

    def test_partial_cancelled_foreign_or_wrong_attempt_ci_cannot_install(self):
        receipt = {"runId": 123, "runAttempt": 1, "sourceRevision": SOURCE}
        run = {"head_sha": SOURCE, "run_attempt": 1, "path": ".github/workflows/ci-backend.yml",
               "name": "CI — Backend", "status": "completed", "conclusion": "success",
               "head_repository": {"full_name": "RootOne1337/sphere-platform"}}
        with patch.object(installer, "command", return_value=json.dumps(run)):
            installer.check_ci(receipt)
        for key, value in (("head_sha", CURRENT), ("run_attempt", 2), ("path", "other.yml"),
                           ("status", "in_progress"), ("conclusion", "cancelled"),
                           ("head_repository", {"full_name": "foreign/repo"})):
            with self.subTest(key=key), patch.object(installer, "command", return_value=json.dumps(run | {key: value})):
                with self.assertRaises(ValueError):
                    installer.check_ci(receipt)

    def test_schema_dependency_and_bootstrap_changes_are_outside_update_scope(self):
        for name in ("alembic/versions/new.py", "backend/requirements.txt", "backend/main.py", "scripts/create_admin.py",
                     "backend/core/rbac.py", "backend/websocket/connection_manager.py"):
            with self.subTest(name=name), patch.object(installer, "command", return_value=name), \
                    patch.object(installer.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "Unreviewed packaged"):
                    installer.source_boundary(CURRENT, SOURCE, {})
                run.assert_not_called()

    def test_discrete_input_update_admits_only_the_reviewed_router_and_parser(self):
        payload = b"unchanged canonical source\n"
        digest = hashlib.sha256(payload).hexdigest()
        paths = ["backend/api/ws/stream/router.py", "backend/websocket/viewer_input.py"]
        with patch.object(installer, "command", return_value="\n".join(paths)), \
                patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, payload)):
            self.assertEqual(installer.source_boundary(CURRENT, SOURCE,
                {"requirementsSha256": digest, "actionContractSha256": digest}), paths)

    def test_ui_inspection_diagnostics_admits_only_the_reviewed_route_and_scalar_trace(self):
        payload = b"unchanged canonical source\n"
        digest = hashlib.sha256(payload).hexdigest()
        paths = ["backend/api/v1/devices/router.py", "backend/services/ui_inspection_trace.py"]
        with patch.object(installer, "command", return_value="\n".join(paths)), \
                patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, payload)):
            self.assertEqual(installer.source_boundary(CURRENT, SOURCE,
                {"requirementsSha256": digest, "actionContractSha256": digest}), paths)

    def test_source_hash_uses_canonical_git_bytes_and_checks_both_files(self):
        payload = b"canonical\nbytes\n"
        digest = hashlib.sha256(payload).hexdigest()
        receipt = {"requirementsSha256": digest, "actionContractSha256": digest}
        with patch.object(installer, "command", return_value="backend/schemas/dag.py\n"), \
                patch.object(installer.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, payload)) as run:
            self.assertEqual(installer.source_boundary(CURRENT, SOURCE, receipt), ["backend/schemas/dag.py"])
            self.assertEqual(run.call_count, 2)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                installer.source_boundary(CURRENT, SOURCE, receipt | {"requirementsSha256": "0" * 64})

    def test_wrong_database_owner_and_url_are_rejected_before_sql(self):
        postgres = {"Config": {"Labels": {"com.docker.compose.project": installer.PROJECT,
            "com.docker.compose.service": "postgres"}, "Env": ["POSTGRES_DB=example"]}}
        for host in ("other", "postgres/other-db"):
            current = {"Config": {"Env": [f"POSTGRES_URL=postgresql://{host}"]}}
            with self.subTest(host=host), patch.object(installer, "inspect", return_value=postgres), \
                    patch.object(installer, "command") as command:
                with self.assertRaises(ValueError):
                    installer.schema_heads(current)
                command.assert_not_called()
        postgres["Config"]["Labels"]["com.docker.compose.project"] = "foreign"
        with patch.object(installer, "inspect", return_value=postgres), patch.object(installer, "command") as command:
            with self.assertRaises(ValueError):
                installer.schema_heads({})
            command.assert_not_called()

    def test_schema_read_is_single_head_and_never_migration(self):
        postgres = {"Config": {"Labels": {"com.docker.compose.project": installer.PROJECT,
            "com.docker.compose.service": "postgres"}, "Env": ["POSTGRES_DB=example"]}}
        current = {"Config": {"Env": ["POSTGRES_URL=postgresql://postgres/example"]}}
        with patch.object(installer, "inspect", return_value=postgres), \
                patch.object(installer, "command", return_value="012_head\n") as command:
            self.assertEqual(installer.schema_heads(current), ["012_head"])
            self.assertIn("SELECT version_num", command.call_args.args[0][-1])
            self.assertNotIn("upgrade", " ".join(command.call_args.args[0]))
        for output in ("", "head1\nhead2", "unexpected value"):
            with self.subTest(output=output), patch.object(installer, "inspect", return_value=postgres), \
                    patch.object(installer, "command", return_value=output), self.assertRaises(ValueError):
                installer.schema_heads(current)

    def test_gateway_requires_dependencies_exact_source_and_bounded_payload(self):
        class Response(io.BytesIO):
            status = 200
        good = [{"checks": {"postgres": "ok", "redis": "ok"}}, {"service": "backend-api", "revision": SOURCE}]
        with patch.object(installer.urllib.request, "urlopen", side_effect=[Response(json.dumps(p).encode()) for p in good]):
            installer.readiness_once(SOURCE)
        for payloads in ([{"checks": {"postgres": "ok"}}], [good[0], good[1] | {"revision": CURRENT}],
                         ["x" * 8193]):
            with self.subTest(payloads=payloads), patch.object(installer.urllib.request, "urlopen",
                    side_effect=[Response(json.dumps(p).encode()) for p in payloads]), self.assertRaises(ValueError):
                installer.readiness_once(SOURCE)

    def test_only_readiness_is_retried_and_failure_remains_visible(self):
        with patch.object(installer, "readiness_once", side_effect=[OSError(), ValueError(), None]) as once, \
                patch.object(installer.time, "sleep"):
            installer.ready(SOURCE)
            self.assertEqual(once.call_count, 3)
        with patch.object(installer, "readiness_once", side_effect=OSError()) as once, \
                patch.object(installer.time, "sleep"), self.assertRaises(OSError):
            installer.ready(SOURCE)
        self.assertEqual(once.call_count, 8)

    @contextmanager
    def installation(self, *, findings=None, gateway_failure=False, foreign_runtime=False):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary)
            private = root / ".local-pilot"
            private.mkdir()
            artifact = private / "artifact"
            artifact.mkdir()
            compose = private / "compose.yml"
            compose.write_text("services: {}")
            env = private / "pilot.env"
            env.write_text("")
            old, state, calls = configuration(), {"installed": False}, []
            original = {"id": "api-old", "imageId": "old-image", "imageTag": "previous:image"}
            before = {installer.BACKEND: original, installer.POSTGRES: {"id": "pg-original"}, "ui": {"id": "ui-original"}}

            def inspected(name):
                self.assertEqual(name, installer.BACKEND)
                installed = state["installed"]
                return {"Id": "api-new" if installed else "api-old",
                    "Image": "foreign-image" if installed and foreign_runtime else IMAGE if installed else "old-image",
                    "State": {"Health": {"Status": "healthy"}},
                    "Config": {"Env": [f"SPHERE_BUILD_SHA={SOURCE if installed else CURRENT}", "POSTGRES_URL=postgresql://postgres/example"],
                               "Labels": {"com.docker.compose.project": installer.PROJECT,
                               "com.docker.compose.service": "backend",
                               "com.docker.compose.project.config_files": str(compose),
                               "com.docker.compose.project.environment_file": str(env)}}}

            def inventory():
                return before | {installer.BACKEND: {"id": "api-new", "imageId": IMAGE, "imageTag": TAG}} if state["installed"] else before

            def command(args, **kwargs):
                calls.append(args)
                if args[:3] == ["docker", "image", "load"]:
                    return "loaded"
                if args[:3] == ["docker", "image", "inspect"]:
                    return json.dumps([{"Id": IMAGE}])
                if args[:2] == ["docker", "ps"]:
                    return "api-new"
                self.assertEqual(args[:2], ["docker", "compose"])
                if args[-3:] == ["config", "--format", "json"]:
                    return json.dumps(candidate(old) if args.count("--file") == 2 else old)
                self.assertIn("--no-deps", args)
                self.assertIn("--no-build", args)
                self.assertIn("never", args)
                self.assertEqual(args[-1], "backend")
                state["installed"] = args.count("--file") == 2
                return "ready"

            def gateway(source):
                if gateway_failure and source == SOURCE:
                    raise ValueError("gateway failed")

            patches = {"ROOT": root, "PRIVATE": private, "admit": lambda *_: {
                "imageId": IMAGE, "imageTag": TAG, "runId": 123, "archiveBytes": 100},
                "bounded_json": lambda *_: {"migrationHeads": ["head"]}, "check_ci": lambda *_: None,
                "source_boundary": lambda *_: ["backend/schemas/dag.py"], "schema_heads": lambda *_: ["head"],
                "snapshot": inventory, "inspect": inspected, "command": command, "ota_hash": lambda: "catalog",
                "collect": lambda *_: {}, "evaluate": lambda *_: findings or [], "ready": gateway}
            for key, value in patches.items():
                stack.enter_context(patch.object(installer, key, value))
            yield artifact, private, calls, state

    def test_plan_is_read_only_without_load_up_or_gateway_probe(self):
        with self.installation() as (artifact, _, calls, state):
            result = installer.execute(artifact, SOURCE, IMAGE, CURRENT, False)
            self.assertFalse(result["runtimeInstalled"])
            self.assertFalse(state["installed"])
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(args[-3:] == ["config", "--format", "json"] for args in calls))

    def test_resource_incident_prevents_image_load_and_restart(self):
        with self.installation(findings=["volume_not_ready"]) as (artifact, _, calls, state):
            with self.assertRaisesRegex(ValueError, "Host not admitted"):
                installer.execute(artifact, SOURCE, IMAGE, CURRENT, True)
            self.assertFalse(state["installed"])
            self.assertEqual(len(calls), 3)

    def test_migration_mismatch_prevents_even_compose_planning(self):
        with self.installation() as (artifact, _, calls, _), \
                patch.object(installer, "schema_heads", return_value=["different-head"]):
            with self.assertRaisesRegex(ValueError, "Schema migration"):
                installer.execute(artifact, SOURCE, IMAGE, CURRENT, True)
            self.assertEqual(calls, [])

    def test_success_preserves_dependencies_without_claiming_android_execution(self):
        with self.installation() as (artifact, _, calls, state):
            result = installer.execute(artifact, SOURCE, IMAGE, CURRENT, True)
            self.assertTrue(state["installed"])
            self.assertTrue(result["runtimeInstalled"])
            self.assertEqual(result["otherContainersPreserved"], 2)
            self.assertFalse(result["schemaMigrationPerformed"])
            self.assertFalse(result["liveContractVerified"])
            self.assertFalse(result["agentReconnectVerified"])
            self.assertEqual(sum("up" in c for c in calls), 1)

    def test_gateway_failure_rolls_back_only_owned_api_and_never_sql(self):
        with self.installation(gateway_failure=True) as (artifact, private, calls, state):
            with self.assertRaisesRegex(ValueError, "gateway failed"):
                installer.execute(artifact, SOURCE, IMAGE, CURRENT, True)
            self.assertFalse(state["installed"])
            self.assertEqual(sum("up" in c for c in calls), 2)
            receipts = list(private.glob("reviewed-backend-install-*/rollback.json"))
            self.assertEqual(len(receipts), 1)
            self.assertFalse(json.loads(receipts[0].read_text())["databaseRollbackPerformed"])

    def test_foreign_image_after_replacement_is_not_stopped_by_rollback(self):
        with self.installation(foreign_runtime=True) as (artifact, private, calls, _):
            with self.assertRaisesRegex(ValueError, "image/readiness"):
                installer.execute(artifact, SOURCE, IMAGE, CURRENT, True)
            self.assertEqual(sum("up" in c for c in calls), 1)
            self.assertEqual(list(private.glob("reviewed-backend-install-*/rollback.json")), [])


if __name__ == "__main__":
    unittest.main()
