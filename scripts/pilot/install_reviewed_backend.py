"""Plan or install one reviewed schema-free contract/control update from CI.

Never builds, migrates, seeds SQL, changes secrets or restarts dependencies.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot.install_reviewed_web import (  # noqa: E402
    command,
    freeze_compose,
    inspect,
    loaded_image_id,
    write,
)
from scripts.pilot.resource_guard import collect, evaluate  # noqa: E402
from scripts.pilot.reviewed_backend_artifact import admit  # noqa: E402
from scripts.pilot.reviewed_image_archive import bounded_json, require  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / ".local-pilot"
PROJECT = "sphere-pilot-20260911"
BACKEND = f"{PROJECT}-backend-1"
POSTGRES = f"{PROJECT}-postgres-1"
APPROVED_PATHS = {
    "backend/api/v1/devices/router.py", "backend/services/ui_inspection_trace.py",
    "backend/api/v1/scripts/router.py", "backend/schemas/action_contract.v1.json",
    "backend/schemas/action_parameters.py", "backend/schemas/dag.py",
    "backend/schemas/script.py", "backend/services/script_service.py",
    "backend/api/ws/stream/router.py", "backend/websocket/viewer_input.py",
    "backend/api/ws/android/router.py", "backend/websocket/startup.py",
    "backend/websocket/continuous_runtime.py", "backend/websocket/continuous_delivery.py",
    "backend/websocket/continuous_lease.py", "backend/websocket/continuous_protocol.py",
    "backend/websocket/continuous_receipts.py", "backend/websocket/frames.py",
    "backend/websocket/continuous_observability.py", "backend/metrics.py",
    "backend/core/config.py", "backend/api/ws/direct/__init__.py",
    "backend/api/ws/direct/router.py", "backend/websocket/direct_probe_protocol.py",
    "backend/websocket/direct_probe_runtime.py",
    "backend/api/v1/batches/router.py", "backend/services/batch_service.py",
    "backend/database/redis_client.py",
}
PACKAGED_PATHS = ["backend", "alembic", "agent-config", "scripts/create_admin.py",
    "scripts/seed_enrollment_key.py", "scripts/backfill_script_metadata.py", "scripts/publish_script_source.py"]


def workspace_path(path: Path, *, private: bool = False) -> Path:
    require(path.absolute().is_relative_to(ROOT.absolute()), "Path outside workspace spelling")
    resolved = path.resolve(strict=True)
    scope = PRIVATE if private else ROOT
    require(resolved.is_relative_to(scope.resolve(strict=True)), "Path outside admitted workspace")
    ancestor = path.absolute()
    while ancestor != ROOT:
        require(not ancestor.is_symlink() and not ancestor.is_junction(), "Linked workspace path rejected")
        ancestor = ancestor.parent
    return resolved


def snapshot() -> dict[str, dict[str, Any]]:
    names = command(["docker", "ps", "--all", "--format", "{{.Names}}"])
    entries = [name for name in names.splitlines() if name]
    require(0 < len(entries) <= 128 and len(set(entries)) == len(entries), "Container inventory budget exceeded")
    result = {}
    for name in entries:
        data = inspect(name)
        result[name] = {"id": data["Id"], "imageId": data["Image"], "imageTag": data["Config"]["Image"],
                        "startedAt": data["State"]["StartedAt"], "status": data["State"]["Status"]}
    require(BACKEND in result and POSTGRES in result, "Owned backend/database absent")
    return result


def preserved(before: dict[str, Any], after: dict[str, Any]) -> None:
    require(before.keys() == after.keys(), "Container inventory changed")
    require(all(before[name] == after[name] for name in before if name != BACKEND), "Another runtime changed")


def probe_environment(device: str | None, disable: bool = False) -> dict[str, str]:
    require(not (device is not None and disable), "Probe enable/disable options are mutually exclusive")
    if disable:
        return {"DIRECT_TRANSPORT_PROBE_ENABLED": "false", "DIRECT_TRANSPORT_PROBE_DEVICE_IDS": "[]"}
    if device is None:
        return {}
    require(isinstance(device, str) and str(UUID(device)) == device, "Expected one canonical probe device UUID")
    return {"DIRECT_TRANSPORT_PROBE_ENABLED": "true", "DIRECT_TRANSPORT_PROBE_DEVICE_IDS": json.dumps([device])}


def validate_delta(old: dict[str, Any], new: dict[str, Any], tag: str,
                   direct_probe_device: str | None = None, disable_direct_probe: bool = False) -> None:
    require(old.get("name") == PROJECT and new.get("name") == PROJECT, "Wrong Compose project")
    require(new["services"]["backend"]["image"] == tag and "build" not in new["services"]["backend"],
            "Candidate image/build recipe mismatch")
    expected = copy.deepcopy(new)
    expected["services"]["backend"]["image"] = old["services"]["backend"]["image"]
    if "build" in old["services"]["backend"]:
        expected["services"]["backend"]["build"] = old["services"]["backend"]["build"]
    admitted_env = probe_environment(direct_probe_device, disable_direct_probe)
    if admitted_env:
        env = expected["services"]["backend"]["environment"]
        old_env = old["services"]["backend"]["environment"]
        require(all(env.get(key) == value for key, value in admitted_env.items()), "Probe opt-in/allowlist mismatch")
        for key in admitted_env:
            if key in old_env:
                env[key] = old_env[key]
            else:
                env.pop(key, None)
    require(expected == old, "Only backend image/build removal and explicit single-device probe are admitted")
    require(not new["services"]["backend"].get("ports"), "Direct backend port rejected")
    require(not new["services"]["backend"].get("user") and not new["services"]["backend"].get("command"),
            "Shipped runtime entry must not be overridden")
    require("SPHERE_BUILD_SHA" not in new["services"]["backend"].get("environment", {}), "Build identity override rejected")
    volumes = new["services"]["backend"].get("volumes", [])
    targets = {"/app/agent-config", "/app/backend/updates", "/var/lib/sphere/device-logs", "/var/lib/sphere/updates"}
    require(isinstance(volumes, list) and all(isinstance(v, dict) for v in volumes), "Unexpected mount format")
    require(len(volumes) == 4 and {v.get("target") for v in volumes} == targets,
            "Packaged source overlay or unknown mount rejected")
    require(next(v for v in volumes if v["target"] == "/app/agent-config").get("read_only") is True,
            "Agent configuration must remain read-only")
    require(not new["services"]["backend"].get("entrypoint"), "Shipped entrypoint override rejected")


def check_ci(receipt: dict[str, Any]) -> None:
    run = json.loads(command(["gh", "api", f"repos/RootOne1337/sphere-platform/actions/runs/{receipt['runId']}"]))
    require(run.get("head_sha") == receipt["sourceRevision"] and run.get("run_attempt") == receipt["runAttempt"],
            "GitHub source/run/attempt mismatch")
    require(run.get("path") == ".github/workflows/ci-backend.yml" and run.get("name") == "CI — Backend",
            "Unexpected backend workflow")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "Complete backend CI not admitted")
    require(run.get("head_repository", {}).get("full_name") == "RootOne1337/sphere-platform", "Unexpected head repository")


def source_boundary(current: str, source: str, receipt: dict[str, Any]) -> list[str]:
    for revision in (current, source):
        require(bool(re.fullmatch(r"[a-f0-9]{40}", revision)), "Expected complete revision boundary")
    changes = command(["git", "diff", "--name-only", current, source, "--", *PACKAGED_PATHS]).splitlines()
    require(set(changes) <= APPROVED_PATHS, "Unreviewed packaged source/dependency/schema change")
    for name, key in [("backend/requirements.txt", "requirementsSha256"),
                      ("backend/schemas/action_contract.v1.json", "actionContractSha256")]:
        # Git bytes avoid workspace CRLF conversion and stdout text normalization.
        result = subprocess.run(["git", "show", f"{source}:{name}"], capture_output=True, timeout=15, check=False)
        require(result.returncode == 0 and 0 < len(result.stdout) <= 256 * 1024,
                "Canonical source unavailable")
        require(hashlib.sha256(result.stdout).hexdigest() == receipt[key], "Artifact dependency/source hash mismatch")
    return changes


def schema_heads(current: dict[str, Any]) -> list[str]:
    postgres = inspect(POSTGRES)
    labels = postgres["Config"]["Labels"]
    require(labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.service") == "postgres", "Wrong database owner")
    env = dict(v.split("=", 1) for v in postgres["Config"]["Env"] if "=" in v)
    api_env = dict(v.split("=", 1) for v in current["Config"]["Env"] if "=" in v)
    url = urlsplit(api_env["POSTGRES_URL"])
    require(url.hostname == "postgres" and unquote(url.path.removeprefix("/")) == env.get("POSTGRES_DB"),
            "API/database identity mismatch")
    output = command(["docker", "exec", POSTGRES, "/bin/sh", "-c",
        'exec psql -X -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -v ON_ERROR_STOP=1 '
        '-c "SELECT version_num FROM alembic_version ORDER BY version_num;"'])
    heads = output.splitlines()
    require(len(heads) == 1 and bool(re.fullmatch(r"[A-Za-z0-9_]{1,128}", heads[0])), "Unknown installed schema head")
    return heads


def ota_hash() -> str:
    path = workspace_path(PRIVATE / "updates/releases.json", private=True)
    require(path.stat().st_size <= 1024 * 1024, "OTA catalog budget exceeded")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def readiness_once(source: str) -> None:
    for path in ("ready", "build"):
        with urllib.request.urlopen(f"http://127.0.0.1:3015/api/v1/health/{path}", timeout=2) as response:
            require(response.status == 200, "Gateway API not ready")
            payload = response.read(8193)
            require(len(payload) <= 8192, "Health response budget exceeded")
            result = json.loads(payload)
        if path == "ready":
            require(result.get("checks") == {"postgres": "ok", "redis": "ok"}, "API dependencies not ready")
        else:
            require(result.get("service") == "backend-api" and result.get("revision") == source,
                    "Gateway served wrong API revision")


def ready(source: str) -> None:
    # Only readiness reads are retried. Nginx may briefly retain the old DNS IP.
    for attempt in range(8):
        try:
            readiness_once(source)
            return
        except (ValueError, OSError, urllib.error.URLError):
            if attempt == 7:
                raise
            time.sleep(2)


def execute(artifact: Path, source: str, expected_image_id: str, expected_current: str, apply: bool,
            direct_probe_device: str | None = None, disable_direct_probe: bool = False) -> dict[str, Any]:
    admitted_env = probe_environment(direct_probe_device, disable_direct_probe)
    require(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", expected_image_id)), "Expected independent CI image ID")
    artifact = workspace_path(artifact, private=True)
    admitted = admit(artifact, source)
    require(admitted["imageId"] == expected_image_id, "Archive image differs from independent CI admission")
    receipt = bounded_json(artifact / "receipt.json", 256 * 1024)
    check_ci(receipt)
    before = snapshot()
    current = inspect(BACKEND)
    require(current["Id"] == before[BACKEND]["id"] and current["State"]["Health"]["Status"] == "healthy",
            "Backend baseline identity/health changed")
    labels = current["Config"]["Labels"]
    require(labels.get("com.docker.compose.project") == PROJECT and labels.get("com.docker.compose.service") == "backend",
            "Wrong backend owner")
    runtime_env = dict(v.split("=", 1) for v in current["Config"]["Env"] if "=" in v)
    require(runtime_env.get("SPHERE_BUILD_SHA") == expected_current, "Backend revision changed before planning")
    changes = source_boundary(expected_current, source, receipt)
    heads = schema_heads(current)
    require(heads == receipt["migrationHeads"], "Schema migration is not admitted by this installer")
    files = labels.get("com.docker.compose.project.config_files", "").split(",")
    require(1 <= len(files) <= 64 and all(files) and len(set(files)) == len(files),
            "Unexpected Compose file inventory")
    env_file = workspace_path(Path(labels["com.docker.compose.project.environment_file"]), private=True)
    cmd = ["docker", "compose", "--project-name", PROJECT, "--env-file", str(env_file)]
    prefix = list(cmd)
    for file in files:
        cmd += ["--file", str(workspace_path(Path(file)))]
    old = json.loads(command(cmd + ["config", "--format", "json"]))
    require(old["services"]["backend"]["image"] == before[BACKEND]["imageTag"], "Baseline Compose/image mismatch")
    require(all(runtime_env.get(k) == v for k, v in old["services"]["backend"].get("environment", {}).items()),
            "Baseline environment differs from Compose")
    output = PRIVATE / f"reviewed-backend-install-{source[:12]}-{uuid4().hex[:8]}"
    output.mkdir()
    override = output / "candidate.yml"
    with override.open("x", encoding="utf-8") as stream:
        stream.write(f"services:\n  backend:\n    image: {admitted['imageTag']}\n    build: !reset null\n")
        if admitted_env:
            stream.write("    environment:\n")
            for key, value in admitted_env.items():
                stream.write(f"      {key}: {json.dumps(value)}\n")
    frozen_cmd = freeze_compose(prefix, old, output / "baseline.json", runner=command)
    candidate_cmd = frozen_cmd + ["--file", str(override)]
    candidate = json.loads(command(candidate_cmd + ["config", "--format", "json"]))
    validate_delta(old, candidate, admitted["imageTag"], direct_probe_device, disable_direct_probe)
    catalog = ota_hash()
    findings = evaluate(collect(ROOT))
    plan = {"sourceRevision": source, "runId": admitted["runId"], "imageId": admitted["imageId"],
        "archiveBytes": admitted["archiveBytes"], "previousBackend": before[BACKEND], "sourceChanges": changes,
        "schemaHeads": heads, "schemaMigrationPerformed": False, "resourceFindings": findings,
        "observedAtUtc": datetime.now(timezone.utc).isoformat(), "applyRequested": apply,
        "previousComposeFileCount": len(files), "candidateComposeFileCount": 2,
        "completeBaselineRoundtripVerified": True,
        "directProbeDevice": direct_probe_device, "directProbeMediaControlEnabled": False,
        "directProbeExplicitlyDisabled": disable_direct_probe,
        "otaCatalogSha256": catalog, "reportDirectory": str(output), "runtimeInstalled": False}
    write(output / "plan.json", plan)
    if not apply:
        return plan
    require(not findings and not evaluate(collect(ROOT)), "Host not admitted before image load")
    preserved(before, snapshot())
    require(inspect(BACKEND)["Id"] == before[BACKEND]["id"] and schema_heads(current) == heads,
            "Backend/database changed before load")
    command(["docker", "image", "load", "--input", str(artifact / "image.tar.gz")], timeout=180)
    image = json.loads(command(["docker", "image", "inspect", admitted["imageTag"]]))[0]
    runtime_id = loaded_image_id(artifact, image, admitted["imageId"])
    require(not evaluate(collect(ROOT)), "Host not admitted before replacement")
    preserved(before, snapshot())
    require(inspect(BACKEND)["Id"] == before[BACKEND]["id"] and schema_heads(current) == heads,
            "Backend/database changed before replacement")
    write(output / "intent.json", {"sourceRevision": source, "beforeBackend": before[BACKEND], "imageId": runtime_id})
    up = ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "--timeout", "35",
          "--wait", "--wait-timeout", "90", "backend"]
    try:
        command(candidate_cmd + up, timeout=150)
        after = snapshot()
        preserved(before, after)
        installed = inspect(BACKEND)
        installed_env = dict(v.split("=", 1) for v in installed["Config"]["Env"] if "=" in v)
        require(all(installed_env.get(key) == value for key, value in
                    candidate["services"]["backend"].get("environment", {}).items()),
                "Installed environment differs from admitted candidate")
        require(installed["Image"] == runtime_id and installed["State"]["Health"]["Status"] == "healthy",
                "Backend image/readiness mismatch")
        require(schema_heads(installed) == heads and ota_hash() == catalog, "SQL schema/OTA catalog changed")
        ready(source)
        result = plan | {"runtimeInstalled": True, "loadedImageId": runtime_id, "installedBackend": after[BACKEND],
            "otherContainersPreserved": len(before) - 1, "liveContractVerified": False, "agentReconnectVerified": False}
        write(output / "installed.json", result)
        return result
    except Exception:
        matches = command(["docker", "ps", "--all", "--filter", f"name=^/{BACKEND}$", "--format", "{{.ID}}"])
        live = inspect(BACKEND) if matches.strip() else None
        owned = live is None or (live["Image"] in (runtime_id, before[BACKEND]["imageId"])
            and live["Config"]["Labels"].get("com.docker.compose.project") == PROJECT
            and live["Config"]["Labels"].get("com.docker.compose.service") == "backend")
        if owned:
            command(cmd + up, timeout=150)
            rollback = inspect(BACKEND)
            require(rollback["Image"] == before[BACKEND]["imageId"] and rollback["State"]["Health"]["Status"] == "healthy",
                    "Backend rollback not admitted")
            require(schema_heads(rollback) == heads and ota_hash() == catalog, "Rollback SQL/OTA preservation not verified")
            preserved(before, snapshot())
            ready(expected_current)
            write(output / "rollback.json", {"previousImageId": before[BACKEND]["imageId"], "ready": True,
                                          "databaseRollbackPerformed": False})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-current-source", required=True)
    parser.add_argument("--apply", action="store_true")
    probe = parser.add_mutually_exclusive_group()
    probe.add_argument("--direct-probe-device", help="Opt in only this canonical UUID to the diagnostic echo canary")
    probe.add_argument("--disable-direct-probe", action="store_true", help="Disable diagnostic probe and empty its allowlist")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.artifact, args.source, args.expected_image_id, args.expected_current_source,
                                 args.apply, args.direct_probe_device, args.disable_direct_probe)))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        print(json.dumps({"runtimeInstalled": None, "state": "not-admitted", "detail": "Review private plan/CI/host evidence"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
