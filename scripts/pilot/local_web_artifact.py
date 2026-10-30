"""Admit a local immutable UI image against full local regressions and packaged probes.

This is an explicit maintainer-local path, never a fabricated hosted Actions run.
It does not load archives, start containers, or install the UI.
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

from scripts.pilot.local_backend_artifact import command, hashed_evidence, private_file
from scripts.pilot.local_ci import jest_counts, validate_source
from scripts.pilot.reviewed_image_archive import bounded_json, require
from scripts.pilot.reviewed_web_artifact import REQUIRED_ROUTES

ROOT = Path(__file__).resolve().parents[2]
RUN = re.compile(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z")


def frontend_run(item: dict, source: str) -> str:
    data = hashed_evidence(item)
    run = data.get("runId")
    require(isinstance(run, str) and RUN.fullmatch(run), "Invalid local executor identity")
    require(item["file"] == f"local-ci/runs/{run}/receipt.json", "Wrong local executor path")
    require(
        data.get("schemaVersion") == 1
        and data.get("state") == "success"
        and data.get("workflowMode") == "maintainer-local-executor"
        and data.get("source", {}).get("sha") == source
        and data.get("source", {}).get("repository") == "RootOne1337/sphere-platform"
        and data.get("publicForkJobsAccepted") is False,
        "Local frontend source/state not admitted",
    )
    profile = data.get("profiles", {}).get("frontend", {})
    require(profile.get("state") == "success", "Complete frontend local suite required")
    tests = profile.get("tests", {})
    require(
        type(tests.get("tests")) is int
        and tests["tests"] > 0
        and tests.get("success") is True
        and tests.get("failures") == 0
        and tests.get("failedSuites") == 0,
        "No executed successful frontend tests",
    )
    require(
        jest_counts(
            private_file(f"local-ci/runs/{run}/jest.json"),
            datetime.fromisoformat(profile["startedAt"]).timestamp(),
        )
        == tests,
        "Frontend test counts differ from original Jest report",
    )
    steps = profile.get("steps")
    required = {
        "action-contract",
        "jest",
        "test_preview_relay.cjs",
        "test_frontend_standalone_probe.mjs",
        "test_package_command_failure.mjs",
        "archive-admission",
        "types",
    }
    require(
        isinstance(steps, list)
        and {step.get("name") for step in steps} == required
        and len(steps) == len(required)
        and all(
            type(step.get("exitCode")) is int
            and step["exitCode"] == 0
            and step.get("timedOut") is False
            for step in steps
        ),
        "Frontend executor steps incomplete",
    )
    publication = profile.get("github", {})
    require(
        publication.get("context") == "Sphere Local / Frontend regressions"
        and publication.get("state") == "success"
        and publication.get("readbackVerified") is True,
        "Local frontend result must be published to GitHub",
    )
    rows = json.loads(
        command(
            [
                "gh",
                "api",
                f"repos/RootOne1337/sphere-platform/commits/{source}/statuses?per_page=100",
            ]
        )
    )
    latest = next((row for row in rows if row.get("context") == publication["context"]), {})
    require(
        latest.get("id") == publication.get("id") and latest.get("state") == "success",
        "Local frontend GitHub result changed",
    )
    return run


def canonical_frontend(source: str) -> bytes:
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "archive", "--format=tar", source, "frontend"],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
        check=False,
    )
    require(
        result.returncode == 0 and 0 < len(result.stdout) <= 32 * 1024 * 1024,
        "Frontend source unavailable",
    )
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        files = 0
        for member in archive:
            require(
                (
                    member.name.startswith("frontend/")
                    or member.name == "frontend"
                    and member.isdir()
                )
                and ".." not in Path(member.name).parts
                and ":" not in member.name
                and "\\" not in member.name
                and (member.isdir() or member.isfile())
                and member.size <= 4 * 1024 * 1024,
                "Invalid frontend source member",
            )
            files += int(member.isfile())
        require(0 < files <= 4096, "Frontend source file budget exceeded")
    return result.stdout


def validate_image(image: dict, source: str, run: str, digest: str, expected_id: str) -> None:
    require(
        image.get("Id") == expected_id
        and image.get("Os") == "linux"
        and image.get("Architecture") == "amd64",
        "Local UI image/platform changed",
    )
    config = image.get("Config", {})
    require(
        isinstance(config, dict)
        and config.get("User") == "1001:1001"
        and config.get("Cmd") == ["node", "server.js"]
        and config.get("WorkingDir") == "/app"
        and config.get("Entrypoint") == ["docker-entrypoint.sh"]
        and config.get("Volumes") in (None, {}),
        "Unexpected local UI runtime",
    )
    labels = config.get("Labels", {})
    require(
        isinstance(labels, dict)
        and labels.get("org.opencontainers.image.revision") == source
        and labels.get("io.sphere.local.run") == run
        and labels.get("io.sphere.local.source") == digest
        and not labels.get("io.sphere.ci.run"),
        "Local UI source/execution binding changed",
    )


def validate_probe(probe: dict, image: str) -> None:
    require(
        probe.get("imageId") == image
        and all(
            probe.get(key) is True
            for key in ("loopbackOnly", "readOnlyContainer", "ownedContainerRemoved")
        )
        and probe.get("browserHydrationVerified") is False
        and probe.get("backendExecutionVerified") is False,
        "Local UI HTTP probe not admitted",
    )
    require(
        type(probe.get("clientAssetsVerified")) is int and 0 < probe["clientAssetsVerified"] <= 512,
        "Local UI assets not admitted",
    )
    pages = probe.get("pages")
    require(isinstance(pages, list) and 0 < len(pages) <= 512, "Invalid local page inventory")
    routes = set()
    for page in pages:
        require(isinstance(page, dict), "Invalid local page receipt")
        route = page.get("route")
        require(
            isinstance(route, str)
            and re.fullmatch(r"/[a-zA-Z0-9/_-]*", route)
            and route not in routes,
            "Invalid local route",
        )
        routes.add(route)
        if route == "/":
            require(
                page.get("status") in (307, 308)
                and page.get("redirect") == "http"
                or page.get("status") == 200
                and page.get("redirect") in ("next-meta", "next-flight"),
                "Local root redirect not admitted",
            )
        else:
            require(page.get("status") == 200, "Local page not admitted")
    require(REQUIRED_ROUTES <= routes, "Local core pages absent")


def admit_local(directory: Path, source: str) -> dict:
    validate_source(ROOT, source, "refs/heads/codex/enterprise-audit-20260905")
    path = private_file(
        (directory.absolute() / "receipt.json").relative_to(ROOT / ".local-pilot").as_posix()
    )
    receipt = bounded_json(path, 256 * 1024)
    require(
        isinstance(receipt, dict)
        and receipt.get("schemaVersion") == 1
        and receipt.get("kind") == "sphere-local-web"
        and receipt.get("sourceRevision") == source
        and receipt.get("runtimeInstalled") is False
        and receipt.get("repository") == "RootOne1337/sphere-platform"
        and receipt.get("archivesCreated") == 0,
        "Invalid local UI receipt",
    )
    run = frontend_run(receipt.get("localExecution"), source)
    digest = hashlib.sha256(canonical_frontend(source)).hexdigest()
    require(receipt.get("sourceArchiveSha256") == digest, "Local frontend source hash mismatch")
    spec = hashed_evidence(receipt.get("buildBinding"))
    image = receipt.get("image", {})
    image_id = image.get("id", "")
    require(
        isinstance(image_id, str)
        and re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
        and image.get("tag") == f"sphere-review-frontend:{source}",
        "Invalid local image identity",
    )
    require(
        spec.get("sourceRevision") == source
        and spec.get("imageId") == image_id
        and spec.get("sourceArchiveSha256") == digest
        and spec.get("runId") == run
        and type(spec.get("exitCode")) is int
        and spec["exitCode"] == 0,
        "Local build/source binding mismatch",
    )
    actual = json.loads(command(["docker", "image", "inspect", image["tag"]]))[0]
    validate_image(actual, source, run, digest, image_id)
    probe = hashed_evidence(receipt.get("httpProbe"))
    validate_probe(probe, image_id)
    return dict(
        sourceRevision=source,
        imageId=image_id,
        imageTag=image["tag"],
        runId=run,
        archiveBytes=0,
        archivesCreated=0,
        localExecutionAdmitted=True,
        runtimeInstalled=False,
        pages=len(probe["pages"]),
        clientAssets=probe["clientAssetsVerified"],
    )
