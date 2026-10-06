"""Hosted CI: retain the already-probed production image, without another build."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Timer
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.pilot.reviewed_backend_artifact import (  # noqa: E402
    COMPRESSED_LIMIT,
    EXPANDED_LIMIT,
    admit,
)
from scripts.pilot.reviewed_image_archive import bounded_json, require  # noqa: E402


def command(args: list[str], *, timeout: int = 60) -> str:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False)
    require(result.returncode == 0 and len(result.stdout.encode()) <= 256 * 1024,
            f"{args[0]} command failed or output exceeded budget")
    return result.stdout.strip()


def check_probes(runtime: Any, metrics: Any, image_id: str) -> None:
    require(isinstance(runtime, dict) and runtime.get("image_id") == image_id
            and type(runtime.get("exit_code")) is int and runtime["exit_code"] == 0
            and runtime.get("containers_removed") is True and runtime.get("action_contract_verified") is True
            and runtime.get("network_internal") is True and runtime.get("host_ports") == []
            and runtime.get("source_mount") is False and runtime.get("api_listener") is False
            and runtime.get("environment") == "development", "Packaged runtime probe mismatch")
    require(isinstance(metrics, dict) and metrics.get("image_id") == image_id
            and metrics.get("passed") is True and metrics.get("container_removed") is True
            and metrics.get("host_ports") == [] and metrics.get("network") == "none"
            and metrics.get("backend_source_mount") is False and metrics.get("pilot_modified") is False,
            "Packaged metrics probe mismatch")


def save_archive(image: str, path: Path) -> dict[str, Any]:
    # Stream to bounded gzip; never keep a second, uncompressed image on disk.
    process = subprocess.Popen(["docker", "image", "save", image], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = Timer(180, process.kill)
    deadline.daemon = True
    deadline.start()
    owned = False
    try:
        require(process.stdout is not None, "Image save pipe missing")
        expanded = 0
        with path.open("xb") as target:
            owned = True
            with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0, compresslevel=1) as compressed:
                for chunk in iter(lambda: process.stdout.read(1024 * 1024), b""):
                    expanded += len(chunk)
                    require(expanded <= EXPANDED_LIMIT, "Uncompressed image budget exceeded")
                    compressed.write(chunk)
                    target.flush()
                    require(target.tell() <= COMPRESSED_LIMIT, "Compressed image budget exceeded")
        require(process.wait(timeout=10) == 0 and expanded > 0, "Image save failed")
        require(0 < path.stat().st_size <= COMPRESSED_LIMIT, "Compressed image budget exceeded")
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        # Only this owned file was created with exclusive open in a fresh CI dir.
        if owned:
            path.unlink(missing_ok=True)
        raise
    finally:
        deadline.cancel()
        if process.stdout:
            process.stdout.close()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
            "maxExpandedBytes": EXPANDED_LIMIT}


def package() -> dict[str, Any]:
    require(os.environ.get("GITHUB_ACTIONS") == "true" and sys.platform == "linux", "Hosted Linux CI packaging only")
    require(os.environ.get("GITHUB_REPOSITORY") == "RootOne1337/sphere-platform", "Wrong repository")
    source = command(["git", "rev-parse", "HEAD"])
    require(bool(re.fullmatch(r"[a-f0-9]{40}", source)) and source == os.environ.get("SPHERE_BUILD_SHA"),
            "Source/build revision mismatch")
    run, attempt = os.environ.get("SPHERE_CI_RUN_ID", ""), os.environ.get("SPHERE_CI_RUN_ATTEMPT", "")
    require(bool(re.fullmatch(r"[1-9][0-9]*", run)) and bool(re.fullmatch(r"[1-9][0-9]*", attempt)), "Invalid CI identity")
    image = f"sphere-reviewed-backend:{source}"
    image_id = command(["docker", "image", "inspect", "--format", "{{.Id}}", image])
    require(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)), "Invalid image ID")
    runtime = bounded_json(ROOT / "image-runtime-evidence/image-runtime-summary.json", 256 * 1024)
    metrics = bounded_json(ROOT / "multiprocess-metrics-evidence/summary.json", 256 * 1024)
    check_probes(runtime, metrics, image_id)
    output = command(["docker", "run", "--rm", "--network", "none", "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,nosuid,nodev,size=16m",
        "-e", "ENVIRONMENT=development", "-e", "JWT_SECRET_KEY=isolated-migration-head-not-a-real-secret",
        image_id, "python", "-m", "alembic", "-c", "alembic/alembic.ini", "heads"])
    heads = re.findall(r"^([A-Za-z0-9_]+) (?:\([^)]+\) )*\(head\)$", output, flags=re.M)
    require(len(heads) == 1, "Expected one packaged migration head")
    folder = ROOT / "reviewed-backend"
    folder.mkdir(exist_ok=False)
    receipt = {"schemaVersion": 1, "kind": "sphere-reviewed-backend", "sourceRevision": source,
        "runId": int(run), "runAttempt": int(attempt), "repository": "RootOne1337/sphere-platform",
        "observedAtUtc": datetime.now(timezone.utc).isoformat(),
        "image": {"tag": image, "id": image_id, "os": "linux", "architecture": "amd64"},
        "archive": save_archive(image, folder / "image.tar.gz"), "migrationHeads": heads,
        "requirementsSha256": hashlib.sha256((ROOT / "backend/requirements.txt").read_bytes()).hexdigest(),
        "actionContractSha256": hashlib.sha256((ROOT / "backend/schemas/action_contract.v1.json").read_bytes()).hexdigest(),
        "probe": {"isolatedRuntimeVerified": True, "actionContractVerified": True, "actionContractVersion": "1.0",
            "multiprocessMetricsVerified": True, "throwawayContainersRemoved": True, "readOnlyApplication": True,
            "hostPorts": [], "environment": "development", "productionRoleRolloutVerified": False,
            "androidExecutionVerified": False, "liveApiVerified": False}, "runtimeInstalled": False}
    with (folder / "receipt.json").open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, indent=2) + "\n")
    return admit(folder, source)


if __name__ == "__main__":
    try:
        print(json.dumps(package()))
    except (ValueError, OSError, subprocess.SubprocessError, TypeError, KeyError):
        print(json.dumps({"artifactAdmitted": False, "runtimeInstalled": False}))
        raise SystemExit(2) from None
