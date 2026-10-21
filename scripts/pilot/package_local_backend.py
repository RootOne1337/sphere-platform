"""Build and probe a schema/dependency-preserving local backend update.

Consumes a full successful local CI receipt. Does not replace the running API,
write a Docker archive, migrate live SQL, or download/install dependencies.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot import install_reviewed_backend as installer
from scripts.pilot.local_backend_artifact import (
    ROOT,
    admit_local,
    check_local_run,
    command,
    source_archive,
    source_files,
    verify_image_source,
)
from scripts.pilot.local_ci import execution_lock, validate_source
from scripts.pilot.resource_guard import admitted_findings, collect, evaluate
from scripts.pilot.reviewed_image_archive import require


def evidence(path: Path) -> dict:
    resolved = installer.workspace_path(path, private=True)
    require(resolved.stat().st_size <= 1024 * 1024, "Evidence exceeds budget")
    return {"file": resolved.relative_to(ROOT / ".local-pilot").as_posix(),
            "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}


def build_spec(parent_tag: str, source: str, run: str, *, catalog: bool = False) -> str:
    # parent_tag is generated from an admitted image ID, never user shell text.
    copy = "source/ /app/" if catalog else "backend/ /app/backend/"
    return (f"FROM {parent_tag}\nCOPY --chown=sphere:sphere {copy}\n"
            f"ENV SPHERE_BUILD_SHA={source}\nLABEL org.opencontainers.image.revision=\"{source}\" "
            f"io.sphere.local.run=\"{run}\" io.sphere.ci.run=\"\" io.sphere.ci.attempt=\"\"\n")


def package(source: str, expected_current: str, execution: Path, output: Path,
            *, allow_degraded_volume: bool = False, catalog: bool = False) -> dict:
    validate_source(ROOT, source, "refs/heads/codex/enterprise-audit-20260905")
    execution_binding = evidence(execution)
    run = check_local_run(execution_binding, source)
    output = output.absolute()
    require(output.parent == ROOT / ".local-pilot" and not output.exists(), "Fresh private output directory required")
    with execution_lock(ROOT / ".local-pilot/local-backend-package.lock"):
        findings = evaluate(collect(ROOT))
        require(not admitted_findings(findings, allow_degraded_volume=allow_degraded_volume), "Host resources not admitted")
        before = installer.snapshot()
        base = installer.inspect(installer.BACKEND)
        env = dict(v.split("=", 1) for v in base["Config"]["Env"] if "=" in v)
        require(base["State"]["Health"]["Status"] == "healthy" and env.get("SPHERE_BUILD_SHA") == expected_current,
                "Installed API source/health changed")
        require(base["Config"]["Labels"].get("com.docker.compose.project") == installer.PROJECT
                and base["Config"]["Labels"].get("com.docker.compose.service") == "backend", "Wrong parent image owner")
        raw = source_archive(source)
        expected = source_files(raw)
        hashes = {"requirementsSha256": expected["backend/requirements.txt"],
                  "actionContractSha256": expected["backend/schemas/action_contract.v1.json"]}
        transition = None
        if catalog:
            from scripts.pilot import vpn_catalog_release
            vpn_catalog_release.source_boundary(expected_current, source, hashes)
            transition = vpn_catalog_release.transition()
            require(installer.schema_heads(base) == transition["from"],
                    "Catalog migration baseline changed")
        else:
            installer.source_boundary(expected_current, source, hashes)
        require(not command(["git", "diff", "--name-only", "--diff-filter=D", expected_current, source, "--", "backend"]),
                "Source deletions need a fresh full image build")
        verify_image_source(base["Image"], source_files(source_archive(expected_current)))
        output.mkdir(exist_ok=False)
        context = output / "context"
        context.mkdir()
        source_dir = context / "source" if catalog else context
        source_dir.mkdir(exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(source_dir, filter="data")
        parent_tag = "sphere-local-backend-parent:" + base["Image"].split(":")[1]
        if not command(["docker", "image", "ls", "-q", "--filter", f"reference={parent_tag}"]):
            command(["docker", "tag", base["Image"], parent_tag])
        require(json.loads(command(["docker", "image", "inspect", parent_tag]))[0]["Id"] == base["Image"],
                "Parent tag identity mismatch")
        (context / "Dockerfile.local").write_text(build_spec(parent_tag, source, run, catalog=catalog), encoding="utf-8")
        tag = f"sphere-reviewed-backend:{source}"
        require(not command(["docker", "image", "ls", "-q", "--filter", f"reference={tag}"]),
                "Candidate tag already exists; never overwrite an admitted artifact")
        with (output / "build.private.log").open("xb") as log:
            result = subprocess.run(["docker", "build", "--network", "none", "--pull=false", "--file",
                str(context / "Dockerfile.local"), "--tag", tag, str(context)], cwd=ROOT,
                stdout=log, stderr=subprocess.STDOUT, timeout=180, check=False)
        require(result.returncode == 0, "Local image build failed; private log retained")
        image = json.loads(command(["docker", "image", "inspect", tag]))[0]
        parent = json.loads(command(["docker", "image", "inspect", base["Image"]]))[0]
        require(image["RootFS"]["Layers"][:-1] == parent["RootFS"]["Layers"], "Parent dependency layers changed")
        verify_image_source(image["Id"], expected)
        probe_env = os.environ | {
            "SPHERE_AUDIT_POSTGRES_IMAGE": "postgres@sha256:5fe8ca7fc662071188c30271cb870d1ce9a6ec4578c934b064697ae77a9241e1",
            "SPHERE_AUDIT_REDIS_IMAGE": "redis@sha256:84bab713067f5494d94c24e99ae3fa3ae2388c037152edcbcf301f7cfaeb3048",
        }
        for script, folder, extra in [("run_backend_runtime_probe.py", "runtime", []),
                                      ("run_multiprocess_metrics_probe.py", "metrics", ["--recycles", "2"])]:
            require(not admitted_findings(evaluate(collect(ROOT)), allow_degraded_volume=allow_degraded_volume),
                    "Host resources not admitted before packaged probe")
            print(json.dumps({"step": script, "state": "started"}), flush=True)
            with (output / (folder + ".private.log")).open("xb") as log:
                result = subprocess.run([sys.executable, str(ROOT / "tests/containers" / script),
                    "--image", image["Id"], "--evidence-dir", str(output / folder), *extra],
                    cwd=ROOT, env=probe_env, stdout=log, stderr=subprocess.STDOUT, timeout=300, check=False)
            require(result.returncode == 0, "Packaged probe failed; private evidence retained")
        live_heads = installer.schema_heads(base)
        if transition:
            require(live_heads == transition["from"], "Installed schema changed during packaging")
        heads = transition["to"] if transition else live_heads
        receipt = {"schemaVersion": 1, "kind": "sphere-local-backend", "sourceRevision": source,
            "repository": "RootOne1337/sphere-platform", "runtimeInstalled": False,
            "observedAtUtc": datetime.now(timezone.utc).isoformat(),
            "image": {"id": image["Id"], "tag": tag}, "localExecution": execution_binding,
            "runtimeProbe": evidence(output / "runtime/image-runtime-summary.json"),
            "metricsProbe": evidence(output / "metrics/summary.json"), "migrationHeads": heads,
            "parentImageId": base["Image"], "parentSource": expected_current,
            "dependencyInstallPerformed": False, "buildNetwork": "none", "archivesCreated": 0, **hashes}
        if transition:
            receipt["schemaTransition"] = transition
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        admitted = admit_local(output, source)
        installer.preserved(before, installer.snapshot())
        require(installer.inspect(installer.BACKEND)["Id"] == base["Id"], "API replaced during packaging")
        return admitted | {"directory": str(output), "otherRuntimesPreserved": True, "archivesCreated": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--expected-current-source", required=True)
    parser.add_argument("--execution", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-degraded-volume", action="store_true")
    parser.add_argument("--vpn-catalog", action="store_true", help="Package the one reviewed additive VPN migration; never applies it")
    args = parser.parse_args()
    try:
        result = package(args.source, args.expected_current_source, args.execution, args.output,
                         allow_degraded_volume=args.allow_degraded_volume, catalog=args.vpn_catalog)
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        print(json.dumps({"state": "not-admitted", "runtimeInstalled": False,
                          "detail": "Review local executor and private packaged evidence"}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
