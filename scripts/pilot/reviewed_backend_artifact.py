"""Admit a reviewed backend archive without extracting or installing it."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tarfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot.reviewed_image_archive import admit_archive, bounded_json, require  # noqa: E402

COMPRESSED_LIMIT = 300 * 1024 * 1024
EXPANDED_LIMIT = 1024 * 1024 * 1024
JSON_LIMIT = 1024 * 1024
COMMAND = ["gunicorn", "backend.main:app", "--config", "backend/gunicorn_conf.py",
           "--worker-class", "uvicorn.workers.UvicornWorker", "--workers", "4",
           "--bind", "0.0.0.0:8000", "--graceful-timeout", "30", "--timeout", "120",
           "--keep-alive", "65", "--max-requests", "10000", "--max-requests-jitter", "1000",
           "--access-logfile", "-"]


def admit(directory: Path, source: str) -> dict[str, Any]:
    require(bool(re.fullmatch(r"[a-f0-9]{40}", source)), "Expected full source revision")
    directory = directory.resolve(strict=True)
    receipt = bounded_json(directory / "receipt.json", 256 * 1024)
    require(isinstance(receipt, dict) and receipt.get("schemaVersion") == 1, "Invalid receipt schema")
    require(receipt.get("kind") == "sphere-reviewed-backend", "Wrong artifact kind")
    require(receipt.get("sourceRevision") == source, "Source revision mismatch")
    require(receipt.get("repository") == "RootOne1337/sphere-platform", "Repository mismatch")
    for key in ("runId", "runAttempt"):
        require(type(receipt.get(key)) is int and receipt[key] > 0, "Invalid CI identity")
    require(receipt.get("runtimeInstalled") is False, "Artifact cannot prove runtime installation")
    image = receipt.get("image", {})
    tag = f"sphere-reviewed-backend:{source}"
    require(isinstance(image, dict) and image.get("tag") == tag, "Unexpected image tag")
    image_id = image.get("id", "")
    require(isinstance(image_id, str) and bool(re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)), "Invalid image digest")
    require(image.get("os") == "linux" and image.get("architecture") == "amd64", "Wrong platform")
    probe = receipt.get("probe", {})
    require(isinstance(probe, dict), "Invalid packaged probe")
    for flag in ("isolatedRuntimeVerified", "actionContractVerified", "multiprocessMetricsVerified",
                 "throwawayContainersRemoved", "readOnlyApplication"):
        require(probe.get(flag) is True, "Incomplete packaged runtime admission")
    require(probe.get("hostPorts") == [] and probe.get("environment") == "development",
            "Packaged probe must remain isolated")
    for flag in ("productionRoleRolloutVerified", "androidExecutionVerified", "liveApiVerified"):
        require(probe.get(flag) is False, "Probe cannot imply live admission")
    require(probe.get("actionContractVersion") == "1.0", "Unknown action contract")
    heads = receipt.get("migrationHeads")
    require(isinstance(heads, list) and len(heads) == 1 and isinstance(heads[0], str)
            and bool(re.fullmatch(r"[A-Za-z0-9_]{1,128}", heads[0])), "Expected one packaged migration head")
    for key in ("requirementsSha256", "actionContractSha256"):
        require(isinstance(receipt.get(key), str) and bool(re.fullmatch(r"[a-f0-9]{64}", receipt[key])),
                "Missing source/dependency boundary")
    config, size = admit_archive(directory, receipt.get("archive"), image_id, tag,
        compressed_limit=COMPRESSED_LIMIT, expanded_limit=EXPANDED_LIMIT, json_limit=JSON_LIMIT)
    runtime = config.get("config", {})
    require(isinstance(runtime, dict) and runtime.get("User") == "sphere", "Expected shipped unprivileged user")
    require(runtime.get("Cmd") == COMMAND and runtime.get("WorkingDir") == "/app"
            and runtime.get("Entrypoint") == ["/bin/sh", "/app/backend/docker-entrypoint.sh"]
            and runtime.get("Volumes") in (None, {}), "Unexpected backend entry")
    labels = runtime.get("Labels", {})
    require(isinstance(labels, dict) and labels.get("org.opencontainers.image.revision") == source
            and labels.get("io.sphere.ci.run") == str(receipt["runId"])
            and labels.get("io.sphere.ci.attempt") == str(receipt["runAttempt"]), "Image CI/source binding mismatch")
    env = runtime.get("Env")
    require(isinstance(env, list) and len(env) <= 128 and all(isinstance(v, str) for v in env)
            and len([v for v in env if v.startswith("SPHERE_BUILD_SHA=")]) == 1
            and f"SPHERE_BUILD_SHA={source}" in env, "Image build revision mismatch")
    return {"sourceRevision": source, "imageId": image_id, "imageTag": tag, "archiveBytes": size,
            "runId": receipt["runId"], "runAttempt": receipt["runAttempt"], "migrationHeads": heads,
            "archiveAdmitted": True, "runtimeInstalled": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(admit(args.directory, args.source)))
    except (ValueError, OSError, tarfile.TarError, TypeError, KeyError):
        print(json.dumps({"archiveAdmitted": False, "runtimeInstalled": False}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
