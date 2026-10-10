"""Plan, or explicitly install, one CI-admitted review UI without rebuilding."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot.resource_guard import collect, evaluate  # noqa: E402
from scripts.pilot.reviewed_web_artifact import admit, bounded_json, require  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PRIVATE = ROOT / ".local-pilot"
PROJECT = "sphere-review-20261002"
UI = f"{PROJECT}-review-ui-1"


def command(args: list[str], *, timeout: int = 30) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    # Never disclose config/environment/native stderr in operational output.
    require(result.returncode == 0 and len(result.stdout.encode()) <= 2 * 1024 * 1024,
            f"{args[0]} command failed or output exceeded budget")
    return result.stdout


def private_path(path: Path) -> Path:
    resolved = path.resolve(strict=True)
    require(resolved.is_relative_to(PRIVATE.resolve(strict=True)), "Path must remain in .local-pilot")
    ancestor = path.absolute()
    while ancestor != ROOT:
        require(not ancestor.is_symlink() and not ancestor.is_junction(), "Linked private path rejected")
        ancestor = ancestor.parent
    return resolved


def inspect(name: str) -> dict[str, Any]:
    data = json.loads(command(["docker", "inspect", name]))
    require(isinstance(data, list) and len(data) == 1, "Ambiguous container identity")
    return data[0]


def snapshot() -> dict[str, dict[str, Any]]:
    names = command(["docker", "ps", "--all", "--format", "{{.Names}}"])
    names = [name for name in names.splitlines() if name]
    require(0 < len(names) <= 128 and len(set(names)) == len(names), "Container inventory budget exceeded")
    result = {}
    for name in names:
        data = inspect(name)
        result[name] = {"id": data["Id"], "imageId": data["Image"], "imageTag": data["Config"]["Image"],
                        "startedAt": data["State"]["StartedAt"], "status": data["State"]["Status"]}
    require(UI in result, "Review UI missing")
    return result


def validate_delta(old: dict[str, Any], new: dict[str, Any], tag: str) -> None:
    require(old.get("name") == PROJECT and new.get("name") == PROJECT, "Wrong Compose project")
    require(new["services"]["review-ui"]["image"] == tag, "Candidate image mismatch")
    require("build" not in new["services"]["review-ui"], "A reviewed image must not keep a stale local build recipe")
    expected = copy.deepcopy(new)
    expected["services"]["review-ui"]["image"] = old["services"]["review-ui"]["image"]
    if "build" in old["services"]["review-ui"]:
        expected["services"]["review-ui"]["build"] = old["services"]["review-ui"]["build"]
    require(expected == old, "Compose delta must contain only review-ui image/build removal")
    gateway = new["services"]["review-gateway"]
    require(any(port.get("published") == "3015" for port in gateway.get("ports", [])), "3015 binding absent")
    require(all(port.get("host_ip") == "127.0.0.1" for port in gateway["ports"]), "Non-loopback gateway rejected")
    require(not new["services"]["review-ui"].get("ports"), "Direct UI port rejected")


def preserved(before: dict[str, Any], after: dict[str, Any]) -> None:
    require(before.keys() == after.keys(), "Container inventory changed")
    require(all(before[name] == after[name] for name in before if name != UI), "Another runtime changed")


def check_ci(receipt: dict[str, Any]) -> None:
    run = json.loads(command(["gh", "api", f"repos/RootOne1337/sphere-platform/actions/runs/{receipt['runId']}"]))
    require(run.get("head_sha") == receipt["sourceRevision"] and run.get("run_attempt") == receipt["runAttempt"],
            "GitHub run/source/attempt mismatch")
    require(run.get("path") == ".github/workflows/ci-frontend.yml" and run.get("name") == "CI — Frontend",
            "Unexpected workflow identity")
    require(run.get("status") == "completed" and run.get("conclusion") == "success", "CI run not admitted")


def catalog_hash() -> str:
    path = private_path(PRIVATE / "updates/releases.json")
    require(path.stat().st_size <= 1024 * 1024, "OTA catalog budget exceeded")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def loaded_image_id(artifact: Path, image: dict[str, Any], config_id: str) -> str:
    """Bind Docker's config or containerd manifest ID to the admitted config."""
    actual = image.get("Id")
    if actual == config_id:
        return config_id
    require(isinstance(actual, str) and bool(re.fullmatch(r"sha256:[a-f0-9]{64}", actual)),
            "Invalid loaded image identity")
    descriptor = image.get("Descriptor", {})
    media_type = "application/vnd.oci.image.manifest.v1+json"
    require(isinstance(descriptor, dict) and descriptor.get("digest") == actual and descriptor.get("mediaType") == media_type,
            "Unexpected loaded image descriptor")
    expected_member = "blobs/sha256/" + actual.removeprefix("sha256:")
    with tarfile.open(artifact / "image.tar.gz", mode="r|gz") as bundle:
        for member in bundle:
            if member.name != expected_member:
                continue
            require(member.isfile() and 0 < member.size <= 256 * 1024, "Invalid image manifest member")
            stream = bundle.extractfile(member)
            require(stream is not None, "Unreadable image manifest")
            payload = stream.read(256 * 1024 + 1)
            require(len(payload) == member.size and "sha256:" + hashlib.sha256(payload).hexdigest() == actual,
                    "Loaded manifest digest mismatch")
            manifest = json.loads(payload)
            require(isinstance(manifest, dict) and manifest.get("schemaVersion") == 2
                    and manifest.get("mediaType") == media_type and isinstance(manifest.get("config"), dict)
                    and manifest["config"].get("digest") == config_id,
                    "Loaded manifest does not bind the admitted config")
            return actual
    raise ValueError("Loaded image manifest absent from admitted archive")


def write(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    require(len(text.encode()) <= 256 * 1024, "Operational receipt budget exceeded")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def freeze_compose(prefix: list[str], baseline: dict[str, Any], path: Path,
                   *, runner: Callable[[list[str]], str] | None = None) -> list[str]:
    """Collapse historical overrides, checking the complete resolved model.

    Resolved environment/command values may contain literal dollars. Escape
    them before Compose reads this private snapshot a second time. Secrets
    remain in the same private report scope, never in operational output.
    """
    def escape(value: Any, keys: tuple[str, ...] = ()) -> Any:
        # Compose's resolved shell fields retain $$ escaping in its JSON model;
        # environment strings are already unescaped. Do not double shell escapes.
        if (len(keys) == 3 and keys[0] == "services" and keys[2] in {"command", "entrypoint"}
                or len(keys) == 4 and keys[0] == "services" and keys[2:] == ("healthcheck", "test")):
            return value
        if isinstance(value, str):
            return value.replace("$", "$$")
        if isinstance(value, list):
            return [escape(item, keys) for item in value]
        if isinstance(value, dict):
            return {key: escape(item, keys + (key,)) for key, item in value.items()}
        return value

    write(path, escape(baseline))
    cmd = prefix + ["--file", str(path)]
    restored = json.loads((runner or command)(cmd + ["config", "--format", "json"]))
    require(restored == baseline, "Frozen Compose differs from complete baseline")
    return cmd


def execute(artifact: Path, source: str, expected_image_id: str, apply: bool) -> dict[str, Any]:
    require(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", expected_image_id)), "Expected independent CI image digest")
    artifact = private_path(artifact)
    admitted = admit(artifact, source)
    require(admitted["imageId"] == expected_image_id, "Archive image does not match independent CI admission")
    receipt = bounded_json(artifact / "receipt.json", 256 * 1024)
    check_ci(receipt)
    host = collect(ROOT)
    findings = evaluate(host)
    before = snapshot()
    current = inspect(UI)
    require(current["Id"] == before[UI]["id"], "UI changed during planning")
    labels = current["Config"]["Labels"]
    require(labels.get("com.docker.compose.project") == PROJECT
            and labels.get("com.docker.compose.service") == "review-ui", "Wrong UI owner")
    config_files = labels.get("com.docker.compose.project.config_files", "").split(",")
    require(1 <= len(config_files) <= 64 and all(config_files)
            and len(set(config_files)) == len(config_files), "Unexpected Compose inventory")
    files = [private_path(Path(name)) for name in config_files]
    env_file = private_path(Path(labels["com.docker.compose.project.environment_file"]))
    cmd = ["docker", "compose", "--project-name", PROJECT, "--env-file", str(env_file)]
    prefix = list(cmd)
    for file in files:
        cmd += ["--file", str(file)]
    old = json.loads(command(cmd + ["config", "--format", "json"]))
    require(old["services"]["review-ui"]["image"] == before[UI]["imageTag"], "Baseline Compose/image mismatch")
    runtime_env = dict(value.split("=", 1) for value in current["Config"]["Env"] if "=" in value)
    require(all(runtime_env.get(key) == value for key, value in
                old["services"]["review-ui"].get("environment", {}).items()), "Baseline UI environment mismatch")
    output = PRIVATE / f"reviewed-web-install-{source[:12]}-{uuid4().hex[:8]}"
    output.mkdir()
    private_path(output)
    override = output / "candidate.yml"
    # !reset removes the old source recipe: a later --build must never rebuild
    # the previous checkout while reusing the newly admitted image tag.
    with override.open("x", encoding="utf-8") as stream:
        stream.write(f"services:\n  review-ui:\n    image: {admitted['imageTag']}\n    build: !reset null\n")
    frozen_cmd = freeze_compose(prefix, old, output / "baseline.json")
    candidate_cmd = frozen_cmd + ["--file", str(override)]
    candidate = json.loads(command(candidate_cmd + ["config", "--format", "json"]))
    validate_delta(old, candidate, admitted["imageTag"])
    ota_hash = catalog_hash()
    plan = {"sourceRevision": source, "runId": admitted["runId"], "imageId": admitted["imageId"],
            "archiveBytes": admitted["archiveBytes"], "previousUi": before[UI], "containerCount": len(before),
            "observedAtUtc": datetime.now(timezone.utc).isoformat(), "resourceFindings": findings,
            "applyRequested": apply, "onlyUiImageAndBuildRemovalDelta": True, "backendPreserved": True,
            "previousComposeFileCount": len(files), "candidateComposeFileCount": 2,
            "completeBaselineRoundtripVerified": True,
            "otaCatalogSha256": ota_hash, "reportDirectory": str(output), "runtimeInstalled": False}
    write(output / "plan.json", plan)
    if not apply:
        return plan
    require(not findings, "Host not admitted; no image loaded or runtime stopped")
    # Before using --apply on the incident host, operator must also accept the
    # new boot/Wininit repair report per HOST-FILESYSTEM-INCIDENT.md.
    require(not evaluate(collect(ROOT)), "Host changed before image load")
    preserved(before, snapshot())
    command(["docker", "image", "load", "--input", str(artifact / "image.tar.gz")], timeout=180)
    image = json.loads(command(["docker", "image", "inspect", admitted["imageTag"]]))[0]
    runtime_id = loaded_image_id(artifact, image, admitted["imageId"])
    require(not evaluate(collect(ROOT)), "Host changed before UI replacement")
    preserved(before, snapshot())
    require(inspect(UI)["Id"] == before[UI]["id"], "UI changed before replacement")
    write(output / "intent.json", {"sourceRevision": source, "beforeUi": before[UI], "imageId": image["Id"]})
    up = ["up", "-d", "--no-deps", "--no-build", "--wait", "--wait-timeout", "75", "review-ui"]
    try:
        command(candidate_cmd + up, timeout=100)
        after = snapshot()
        preserved(before, after)
        installed = inspect(UI)
        require(installed["Image"] == runtime_id
                and installed["State"]["Health"]["Status"] == "healthy", "UI identity/readiness mismatch")
        require(catalog_hash() == ota_hash, "OTA catalog changed")
        with urllib.request.urlopen("http://127.0.0.1:3015/login", timeout=10) as response:
            require(response.status == 200, "Gateway UI readiness failed")
        result = plan | {"runtimeInstalled": True, "loadedImageId": runtime_id, "installedUi": after[UI],
                         "otherContainersPreserved": len(before) - 1, "browserVerified": False}
        write(output / "installed.json", result)
        return result
    except Exception:
        # Roll back only an image/container still attributable to this attempt.
        matches = command(["docker", "ps", "--all", "--filter", f"name=^/{UI}$", "--format", "{{.ID}}"])
        live = inspect(UI) if matches.strip() else None
        owned = live is None or (live["Image"] in (runtime_id, before[UI]["imageId"])
                                 and live["Config"]["Labels"].get("com.docker.compose.project") == PROJECT)
        if owned:
            command(cmd + up, timeout=100)
            rolled_back = inspect(UI)
            require(rolled_back["Image"] == before[UI]["imageId"]
                    and rolled_back["State"]["Health"]["Status"] == "healthy", "UI rollback not admitted")
            write(output / "rollback.json", {"previousImageId": before[UI]["imageId"], "ready": True})
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-image-id", required=True, help="Image ID from authenticated CI logs/admission, not the downloaded receipt")
    parser.add_argument("--apply", action="store_true", help="Install only after host/postboot acceptance")
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.artifact, args.source, args.expected_image_id, args.apply)))
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        print(json.dumps({"runtimeInstalled": None, "state": "not-admitted", "detail": "Review private plan/CI/host evidence"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
