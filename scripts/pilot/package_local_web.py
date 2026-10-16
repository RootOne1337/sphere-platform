"""Build/probe a trusted local UI image without exporting archives or replacing live containers."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from scripts.pilot import install_reviewed_web as installer
from scripts.pilot.local_ci import execution_lock, validate_source
from scripts.pilot.local_web_artifact import (
    ROOT,
    admit_local,
    canonical_frontend,
    command,
    frontend_run,
)
from scripts.pilot.resource_guard import admitted_findings, collect, evaluate
from scripts.pilot.reviewed_image_archive import require


def evidence(path: Path) -> dict:
    path = installer.private_path(path)
    require(
        path.is_file() and path.stat().st_size <= 1024 * 1024, "Private evidence exceeds budget"
    )
    return dict(
        file=path.relative_to(ROOT / ".local-pilot").as_posix(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def package(
    source: str, execution: Path, output: Path, node: Path, *, allow_degraded_volume: bool = False
) -> dict:
    validate_source(ROOT, source, "refs/heads/codex/enterprise-audit-20260905")
    binding = evidence(execution)
    run = frontend_run(binding, source)
    output = output.absolute()
    require(
        output.parent == ROOT / ".local-pilot" and not output.exists(),
        "Fresh private output directory required",
    )
    require(
        command([str(node.resolve(strict=True)), "--version"]).startswith("v24."), "Node24 required"
    )
    # Packaging tooling itself must be committed, so its exact source can be reviewed separately from the UI.
    tool_paths = [
        "scripts/pilot/package_local_web.py",
        "scripts/pilot/local_web_artifact.py",
        "tests/containers/frontend_local.Dockerfile",
        "tests/containers/probe_local_web_image.mjs",
    ]
    tool_source = command(["git", "rev-parse", "HEAD"])
    for path in tool_paths:
        require(
            command(["git", "cat-file", "-t", tool_source + ":" + path]) == "blob",
            "Uncommitted packaging tool",
        )
    require(not command(["git", "diff", tool_source, "--", *tool_paths]), "Packaging tools changed")
    with execution_lock(ROOT / ".local-pilot/local-web-package.lock"):
        require(
            not admitted_findings(
                evaluate(collect(ROOT)), allow_degraded_volume=allow_degraded_volume
            ),
            "Host resources not admitted",
        )
        before = installer.snapshot()
        current = installer.inspect(installer.UI)
        ota_hash = installer.catalog_hash()
        require(current["State"]["Health"]["Status"] == "healthy", "Existing UI not healthy")
        raw = canonical_frontend(source)
        digest = hashlib.sha256(raw).hexdigest()
        output.mkdir(exist_ok=False)
        context = output / "context"
        context.mkdir()
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archive.extractall(context, filter="data")
        tag = f"sphere-review-frontend:{source}"
        require(
            not command(["docker", "image", "ls", "-q", "--filter", "reference=" + tag]),
            "Candidate tag already exists; never overwrite an admitted image",
        )
        print(json.dumps(dict(step="linux-image-build", state="started")), flush=True)
        with (output / "build.private.log").open("xb") as log:
            build = subprocess.run(
                [
                    "docker",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--pull=false",
                    "--build-arg",
                    "BUILD_SHA=" + source,
                    "--build-arg",
                    "LOCAL_RUN=" + run,
                    "--build-arg",
                    "SOURCE_DIGEST=" + digest,
                    "--file",
                    str(ROOT / "tests/containers/frontend_local.Dockerfile"),
                    "--tag",
                    tag,
                    str(context / "frontend"),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=1800,
                check=False,
            )
        require(build.returncode == 0, "Local UI build failed; private log retained")
        require(
            (output / "build.private.log").stat().st_size <= 8 * 1024 * 1024,
            "Build log exceeds budget",
        )
        image = json.loads(command(["docker", "image", "inspect", tag]))[0]
        build_binding = dict(
            sourceRevision=source,
            sourceArchiveSha256=digest,
            imageId=image["Id"],
            runId=run,
            exitCode=build.returncode,
            toolingSource=tool_source,
            dockerfileSha256=hashlib.sha256((ROOT / tool_paths[2]).read_bytes()).hexdigest(),
        )
        (output / "build-binding.json").write_text(
            json.dumps(build_binding, indent=2) + "\n", encoding="utf-8"
        )
        require(
            not admitted_findings(
                evaluate(collect(ROOT)), allow_degraded_volume=allow_degraded_volume
            ),
            "Host resources not admitted before packaged HTTP probe",
        )
        print(json.dumps(dict(step="packaged-http-probe", state="started")), flush=True)
        with (output / "probe.private.log").open("xb") as log:
            probe = subprocess.run(
                [
                    str(node),
                    str(ROOT / tool_paths[3]),
                    image["Id"],
                    "sphere-local-web-probe-" + uuid4().hex[:16],
                    str(output / "http-probe.json"),
                ],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=240,
                check=False,
            )
        require(probe.returncode == 0, "Packaged UI HTTP probe failed; private log retained")
        receipt = dict(
            schemaVersion=1,
            kind="sphere-local-web",
            sourceRevision=source,
            repository="RootOne1337/sphere-platform",
            runtimeInstalled=False,
            observedAtUtc=datetime.now(timezone.utc).isoformat(),
            image=dict(id=image["Id"], tag=tag),
            localExecution=binding,
            sourceArchiveSha256=digest,
            buildBinding=evidence(output / "build-binding.json"),
            httpProbe=evidence(output / "http-probe.json"),
            archivesCreated=0,
            buildPlatform="linux/amd64",
            toolingSource=tool_source,
        )
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        admitted = admit_local(output, source)
        after = installer.snapshot()
        installer.preserved(before, after)
        require(
            after[installer.UI] == before[installer.UI] and installer.catalog_hash() == ota_hash,
            "Live UI/OTA changed during packaging",
        )
        return admitted | dict(directory=str(output), liveContainersPreserved=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--allow-degraded-volume", action="store_true")
    args = parser.parse_args()
    try:
        result = package(
            args.source,
            args.execution,
            args.output,
            args.node,
            allow_degraded_volume=args.allow_degraded_volume,
        )
    except (ValueError, OSError, subprocess.SubprocessError, KeyError, TypeError):
        print(
            json.dumps(
                dict(
                    state="not-admitted",
                    runtimeInstalled=False,
                    detail="Review private local build/probe evidence",
                )
            )
        )
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
