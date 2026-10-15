"""Validate an already loaded local image; never substitute a local run for hosted CI.

Local admission requires its own explicit mode, exact source files, a successful
full backend executor receipt and isolated packaged probes for this image ID.
No duplicate Docker archive is required on the same host.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from scripts.pilot.local_ci import junit_counts, validate_source
from scripts.pilot.reviewed_backend_artifact import COMMAND
from scripts.pilot.reviewed_image_archive import bounded_json, require

ROOT = Path(__file__).resolve().parents[2]
RUN = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
PACKAGED = ("backend", "alembic", "agent-config", "scripts/create_admin.py",
            "scripts/seed_enrollment_key.py", "scripts/backfill_script_metadata.py", "scripts/publish_script_source.py")


def command(args: list[str], *, timeout: int = 60) -> str:
    result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=timeout, check=False)
    require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024, "Local artifact command failed")
    return result.stdout.decode("utf-8").strip()


def private_file(name: str) -> Path:
    require(isinstance(name, str) and "\\" not in name and ":" not in name and not name.startswith("/")
            and ".." not in Path(name).parts and not Path(name).is_absolute(), "Expected relative private path")
    path = ROOT / ".local-pilot" / name
    resolved = path.resolve(strict=True)
    scope = (ROOT / ".local-pilot").resolve(strict=True)
    require(resolved.is_relative_to(scope) and resolved.is_file(), "Local evidence outside private workspace")
    while path != ROOT:
        require(not path.is_symlink() and not path.is_junction(), "Linked local evidence rejected")
        path = path.parent
    return resolved


def hashed_evidence(item: dict) -> dict:
    require(isinstance(item, dict) and item.keys() == {"file", "sha256"}, "Invalid local evidence binding")
    path = private_file(item["file"])
    require(path.stat().st_size <= 1024 * 1024, "Local evidence exceeds budget")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"], "Local evidence hash mismatch")
    result = bounded_json(path, 1024 * 1024)
    require(isinstance(result, dict), "Local evidence must be an object")
    return result


def check_local_run(item: dict, source: str) -> str:
    data = hashed_evidence(item)
    run = data.get("runId")
    require(isinstance(run, str) and RUN.fullmatch(run), "Invalid local executor identity")
    require(item["file"] == f"local-ci/runs/{run}/receipt.json", "Wrong local executor receipt path")
    require(data.get("schemaVersion") == 1 and data.get("state") == "success"
            and data.get("workflowMode") == "maintainer-local-executor"
            and data.get("source", {}).get("sha") == source
            and data.get("source", {}).get("repository") == "RootOne1337/sphere-platform"
            and data.get("publicForkJobsAccepted") is False, "Local executor source/state not admitted")
    backend = data.get("profiles", {}).get("backend", {})
    require(backend.get("state") == "success" and backend.get("isolatedServicesRemoved") is True,
            "Complete backend local suite required")
    tests = backend.get("tests", {})
    require(type(tests.get("tests")) is int and tests["tests"] > 0
            and type(tests.get("failures")) is int and tests["failures"] == 0
            and type(tests.get("errors")) is int and tests["errors"] == 0
            and type(tests.get("skipped")) is int and 0 <= tests["skipped"] < tests["tests"],
            "No executed successful backend tests")
    require(junit_counts([private_file(f"local-ci/runs/{run}/backend-junit.xml")],
                         datetime.fromisoformat(backend["startedAt"]).timestamp()) == tests,
            "Backend test counts differ from original JUnit")
    steps = backend.get("steps")
    required = {"dependencies", "action-contract", "rls-policy", "fresh-migrations",
                "pytest-real-services", "http-api-documentation"}
    require(isinstance(steps, list) and {s.get("name") for s in steps} == required
            and len(steps) == len(required) and all(type(s.get("exitCode")) is int and s["exitCode"] == 0
                and s.get("timedOut") is False for s in steps), "Backend executor steps incomplete")
    publication = backend.get("github", {})
    require(publication.get("context") == "Sphere Local / Backend regressions"
            and publication.get("state") == "success" and publication.get("readbackVerified") is True,
            "Backend local result must be published to GitHub")
    rows = json.loads(command(["gh", "api", f"repos/RootOne1337/sphere-platform/commits/{source}/statuses?per_page=100"]))
    require(isinstance(rows, list), "Invalid GitHub status inventory")
    latest = next((r for r in rows if r.get("context") == publication["context"]), {})
    require(latest.get("id") == publication.get("id") and latest.get("state") == "success",
            "Local backend GitHub status changed")
    return run


def source_archive(source: str) -> bytes:
    # git archive honors core.autocrlf even without a checkout. Linux image
    # provenance must use canonical source bytes, independent of Windows EOL.
    result = subprocess.run(["git", "-c", "core.autocrlf=false", "archive", "--format=tar", source, *PACKAGED],
                            cwd=ROOT, capture_output=True, timeout=30, check=False)
    require(result.returncode == 0 and 0 < len(result.stdout) <= 32 * 1024 * 1024, "Packaged source archive unavailable")
    return result.stdout


def source_files(raw: bytes) -> dict[str, str]:
    result = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive:
            require(not member.issym() and not member.islnk(), "Linked packaged source rejected")
            if member.isdir():
                continue
            require(member.isfile() and member.size <= 4 * 1024 * 1024 and len(result) < 4096
                    and not Path(member.name).is_absolute() and not member.name.startswith("/")
                    and ".." not in Path(member.name).parts and ":" not in member.name
                    and "\\" not in member.name and member.name not in result, "Invalid packaged source entry")
            stream = archive.extractfile(member)
            require(stream is not None, "Missing packaged file")
            result[member.name] = hashlib.sha256(stream.read()).hexdigest()
    require(bool(result), "Empty packaged source")
    return result


def image_files(image: str) -> dict[str, str]:
    script = ("import pathlib,hashlib,json; roots=" + repr(PACKAGED) + "; files={}; "
              "exec('for name in roots:\\n p=pathlib.Path(name)\\n entries=p.rglob(\"*\") if p.is_dir() else [p]"
              "\\n for f in entries:\\n  if f.is_file(): files[f.as_posix()]=hashlib.sha256(f.read_bytes()).hexdigest()'); "
              "print(json.dumps(files))")
    return json.loads(command(["docker", "run", "--rm", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges", image, "python", "-c", script]))


def verify_image_source(image: str, expected: dict[str, str]) -> None:
    actual = image_files(image)
    require(actual == expected, "Image files differ from exact Git source")


def check_packaged_probes(runtime: dict, metrics: dict, image: str) -> None:
    require(runtime.get("image_id") == image and type(runtime.get("exit_code")) is int and runtime["exit_code"] == 0
            and all(runtime.get(k) is True for k in ("containers_removed", "action_contract_verified", "network_internal"))
            and runtime.get("host_ports") == [] and runtime.get("source_mount") is False
            and runtime.get("api_listener") is False and runtime.get("environment") == "development",
            "Packaged runtime probe not admitted")
    require(metrics.get("image_id") == image and metrics.get("passed") is True
            and metrics.get("container_removed") is True and metrics.get("host_ports") == []
            and metrics.get("network") == "none" and metrics.get("backend_source_mount") is False
            and metrics.get("pilot_modified") is False, "Packaged metrics probe not admitted")


def admit_local(directory: Path, source: str) -> dict:
    validate_source(ROOT, source, "refs/heads/codex/enterprise-audit-20260905")
    receipt_path = private_file((directory.absolute() / "receipt.json").relative_to(ROOT / ".local-pilot").as_posix())
    receipt = bounded_json(receipt_path, 256 * 1024)
    require(isinstance(receipt, dict) and receipt.get("schemaVersion") == 1
            and receipt.get("kind") == "sphere-local-backend"
            and receipt.get("sourceRevision") == source and receipt.get("runtimeInstalled") is False
            and receipt.get("repository") == "RootOne1337/sphere-platform"
            and "archive" not in receipt and "runId" not in receipt and "runAttempt" not in receipt,
            "Local artifact identity mismatch")
    run = check_local_run(receipt.get("localExecution"), source)
    image = receipt.get("image", {})
    tag = f"sphere-reviewed-backend:{source}"
    require(isinstance(image, dict) and image.get("tag") == tag and isinstance(image.get("id"), str)
            and IMAGE.fullmatch(image["id"]), "Local image binding mismatch")
    data = json.loads(command(["docker", "image", "inspect", tag]))
    require(isinstance(data, list) and len(data) == 1 and data[0].get("Id") == image["id"], "Local image missing or replaced")
    parent_id = receipt.get("parentImageId")
    require(isinstance(parent_id, str) and IMAGE.fullmatch(parent_id)
            and isinstance(receipt.get("parentSource"), str)
            and re.fullmatch(r"[0-9a-f]{40}", receipt["parentSource"]), "Local parent identity missing")
    parents = json.loads(command(["docker", "image", "inspect", parent_id]))
    require(isinstance(parents, list) and len(parents) == 1 and parents[0].get("Id") == parent_id,
            "Local parent image missing or replaced")
    layers = parents[0].get("RootFS", {}).get("Layers")
    require(isinstance(layers, list) and bool(layers) and all(isinstance(v, str) and IMAGE.fullmatch(v) for v in layers)
            and data[0].get("RootFS", {}).get("Layers", [])[:-1] == layers,
            "Local image dependency layers differ from admitted parent")
    config = data[0].get("Config", {})
    labels = config.get("Labels", {})
    require(data[0].get("Os") == "linux" and data[0].get("Architecture") == "amd64"
            and config.get("User") == "sphere" and config.get("Cmd") == COMMAND
            and config.get("WorkingDir") == "/app" and config.get("Entrypoint") == ["/bin/sh", "/app/backend/docker-entrypoint.sh"]
            and config.get("Volumes") in (None, {}) and labels.get("org.opencontainers.image.revision") == source
            and labels.get("io.sphere.local.run") == run and labels.get("io.sphere.ci.run") in (None, "")
            and labels.get("io.sphere.ci.attempt") in (None, ""), "Local image runtime contract mismatch")
    env = config.get("Env", [])
    require(isinstance(env, list) and [v for v in env if v.startswith("SPHERE_BUILD_SHA=")] == [f"SPHERE_BUILD_SHA={source}"],
            "Local image revision mismatch")
    expected = source_files(source_archive(source))
    verify_image_source(image["id"], expected)
    for name, key in (("backend/requirements.txt", "requirementsSha256"),
                      ("backend/schemas/action_contract.v1.json", "actionContractSha256")):
        require(receipt.get(key) == expected.get(name), "Local dependency/action hash mismatch")
    check_packaged_probes(hashed_evidence(receipt.get("runtimeProbe")), hashed_evidence(receipt.get("metricsProbe")), image["id"])
    heads = receipt.get("migrationHeads")
    require(isinstance(heads, list) and len(heads) == 1 and isinstance(heads[0], str)
            and re.fullmatch(r"[A-Za-z0-9_]{1,128}", heads[0]), "Invalid local migration head")
    output = command(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "-e", "ENVIRONMENT=development",
        "-e", "JWT_SECRET_KEY=isolated-local-head-check-not-a-secret", image["id"],
        "python", "-m", "alembic", "-c", "alembic/alembic.ini", "heads"])
    require(re.findall(r"^([A-Za-z0-9_]+) (?:\([^)]+\) )*\(head\)$", output, re.M) == heads,
            "Local image migration head mismatch")
    return {"sourceRevision": source, "imageId": image["id"], "imageTag": tag,
            "archiveBytes": 0, "runId": run, "runAttempt": None, "migrationHeads": heads,
            "localArtifact": True, "runtimeInstalled": False}
