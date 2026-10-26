"""Run trusted local regressions and report their exact commit to GitHub.

This is a maintainer-operated executor, not a public self-hosted Actions runner.
It never accepts fork jobs, installs production APKs, or uploads raw test logs.
Packaging/release acceptance remains a separate check.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import admitted_findings, collect, evaluate
from scripts.pilot.windows_ci_job import WindowsChildJob

SHA = re.compile(r"[0-9a-f]{40}\Z")
REPOSITORY = "RootOne1337/sphere-platform"
CONTEXTS = {"frontend": "Sphere Local / Frontend regressions",
            "backend": "Sphere Local / Backend regressions",
            "android": "Sphere Local / Android unit tests"}
LOG_LIMIT = 8 * 1024 * 1024
PG_IMAGE = "public.ecr.aws/docker/library/postgres@sha256:25d430274d8a31184f9435cc5b2f56aff254952065bbbcac0c51acedb5a1d1e7"
REDIS_IMAGE = "public.ecr.aws/docker/library/redis@sha256:84bab713067f5494d94c24e99ae3fa3ae2388c037152edcbcf301f7cfaeb3048"
LOCAL_PG_IMAGE = "postgres@sha256:5fe8ca7fc662071188c30271cb870d1ce9a6ec4578c934b064697ae77a9241e1"


class Refused(RuntimeError):
    """A missing measurement or ambiguous result must not turn green."""


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def command(args: list[str], cwd: Path, *, timeout: int = 30) -> str:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode:
        # No arbitrary subprocess output in a public receipt or exception.
        raise Refused(f"command_failed:{Path(args[0]).name}:{result.returncode}")
    if len(result.stdout) > 2 * 1024 * 1024:
        raise Refused("command_response_oversized")
    return result.stdout.strip()


def git(root: Path, *args: str) -> str:
    return command(["git", *args], root)


def validate_source(root: Path, sha: str, trusted_ref: str) -> dict:
    if not SHA.fullmatch(sha) or not trusted_ref.startswith("refs/heads/"):
        raise Refused("explicit_commit_and_local_trusted_branch_required")
    if git(root, "rev-parse", "--verify", sha + "^{commit}") != sha:
        raise Refused("commit_mismatch")
    git(root, "merge-base", "--is-ancestor", sha, trusted_ref)
    origin = git(root, "remote", "get-url", "origin")
    if origin.lower() not in {f"https://github.com/{REPOSITORY.lower()}.git",
                               f"git@github.com:{REPOSITORY.lower()}.git"}:
        raise Refused("repository_mismatch")
    return {"sha": sha, "tree": git(root, "rev-parse", sha + "^{tree}"),
            "trustedRef": trusted_ref, "repository": REPOSITORY}


def github(root: Path, endpoint: str, payload: dict | None = None) -> object:
    args = ["gh", "api", "-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2026-03-10", endpoint]
    if payload is not None:
        args += ["--method", "POST", "--input", "-"]
    result = subprocess.run(args, cwd=root, input=json.dumps(payload) if payload else None,
                            capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
        raise Refused("github_publication_or_readback_failed")
    return json.loads(result.stdout)


def publish(root: Path, sha: str, profile: str, state: str, description: str,
            target_url: str | None = None) -> dict:
    if not SHA.fullmatch(sha) or profile not in CONTEXTS or state not in {
            "pending", "success", "failure", "error"}:
        raise Refused("invalid_status")
    if target_url and not target_url.startswith(f"https://github.com/{REPOSITORY}/"):
        raise Refused("report_url_outside_repository")
    commit = github(root, f"repos/{REPOSITORY}/commits/{sha}")
    if not isinstance(commit, dict) or commit.get("sha") != sha:
        raise Refused("remote_commit_not_confirmed")
    payload = {"state": state, "context": CONTEXTS[profile], "description": description[:140]}
    if target_url:
        payload["target_url"] = target_url
    created = github(root, f"repos/{REPOSITORY}/statuses/{sha}", payload)
    rows = github(root, f"repos/{REPOSITORY}/commits/{sha}/statuses?per_page=100")
    if not isinstance(created, dict) or not isinstance(rows, list):
        raise Refused("invalid_status_readback")
    latest = next((row for row in rows if row.get("context") == payload["context"]), None)
    if (not latest or latest.get("id") != created.get("id") or
            any(latest.get(key) != value for key, value in payload.items())):
        raise Refused("status_readback_mismatch")
    return {"id": created["id"], "context": payload["context"], "state": state,
            "createdAt": latest.get("created_at"), "readbackVerified": True,
            "targetUrl": latest.get("target_url")}


@contextlib.contextmanager
def execution_lock(path: Path):
    """OS-owned lock also releases after a crashed/killed interpreter."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise Refused("another_local_ci_job_is_running") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def child_environment(root: Path, sha: str) -> dict[str, str]:
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME",
               "LOCALAPPDATA", "APPDATA", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE",
               "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES",
               "COMMONPROGRAMFILES(X86)", "ALLUSERSPROFILE", "SYSTEMDRIVE"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(CI="true", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               PYTHONPATH=str(root) + os.pathsep + str(root / "pc-agent"),
               NEXT_TELEMETRY_DISABLED="1", NEXT_PUBLIC_BUILD_SHA=sha, GIT_SHA=sha,
               DEV_SKIP_AUTH="false", REDIS_PASSWORD="",
               POSTGRES_URL="postgresql+asyncpg://sphere:test_password@127.0.0.1:1/sphere_audit_ci",
               REDIS_URL="redis://127.0.0.1:1/0", SPHERE_RUN_INTEGRATION="0",
               JWT_SECRET_KEY="local_ci_test_jwt_secret_at_least_32_chars",
               WG_ROUTER_URL="http://mock-wg-router", WG_ROUTER_API_KEY="test_key",
               VPN_SERVER_HOSTNAME="localhost", AWG_H1="1111111111", AWG_H2="2222222222",
               AWG_H3="3333333333", AWG_H4="4444444444")
    return env


def stop_child(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=15, check=False)
    else:
        import signal
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


def run_step(args: list[str], cwd: Path, env: dict[str, str], log: Path,
             *, timeout: int = 1200) -> dict:
    """Drain output even past the log cap; terminate the complete child tree."""
    started = time.monotonic()
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS} if os.name == "nt" else {
        "start_new_session": True}
    process = subprocess.Popen(args, cwd=cwd, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, **options)
    try:
        job = WindowsChildJob(process)
    except OSError:
        stop_child(process)
        process.stdout.close()
        raise Refused("owned_process_tree_unavailable") from None
    sizes = {"seen": 0, "saved": 0, "error": None}

    def drain() -> None:
        output = None
        try:
            output = log.open("wb")
        except OSError as error:
            sizes["error"] = type(error).__name__
        while chunk := process.stdout.read1(65536):
            try:
                sizes["seen"] += len(chunk)
                remaining = LOG_LIMIT - sizes["saved"]
                if output and remaining > 0:
                    output.write(chunk[:remaining])
                    sizes["saved"] += min(len(chunk), remaining)
            except OSError as error:
                sizes["error"] = type(error).__name__
                output.close()
                output = None
        if output:
            try:
                output.close()
            except OSError as error:
                sizes["error"] = type(error).__name__

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop_child(process)
    except BaseException:
        stop_child(process)
        raise
    finally:
        job.close()
        reader.join(timeout=10)
        if not reader.is_alive():
            process.stdout.close()
    if reader.is_alive():
        raise Refused("output_reader_not_finished")
    if sizes["error"]:
        raise Refused("local_log_write_failed")
    return {"exitCode": process.returncode, "timedOut": timed_out,
            "elapsedSeconds": round(time.monotonic() - started, 3),
            "logBytes": sizes["saved"], "logTruncated": sizes["seen"] > sizes["saved"]}


def junit_counts(files: list[Path], started_at: float) -> dict:
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not files:
        raise Refused("test_reports_missing")
    for file in files:
        if file.stat().st_size > 16 * 1024 * 1024 or file.stat().st_mtime < started_at - 2:
            raise Refused("stale_or_oversized_test_report")
        raw = file.read_bytes()
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise Refused("unsafe_xml_report")
        tree = ET.fromstring(raw)
        cases = list(tree.iter("testcase"))
        for case in cases:
            total["tests"] += 1
            for key, element in [("failures", "failure"), ("errors", "error"), ("skipped", "skipped")]:
                total[key] += int(case.find(element) is not None)
    if total["tests"] == 0 or total["tests"] == total["skipped"]:
        raise Refused("no_executed_tests")
    return total


def jest_counts(file: Path, started_at: float) -> dict:
    if not file.exists() or file.stat().st_mtime < started_at - 2:
        raise Refused("jest_report_missing_or_stale")
    if file.stat().st_size > 16 * 1024 * 1024:
        raise Refused("jest_report_oversized")
    data = json.loads(file.read_text(encoding="utf-8"))
    keys = ["numTotalTests", "numPassedTests", "numFailedTests", "numPendingTests",
            "numTotalTestSuites", "numFailedTestSuites"]
    if any(type(data.get(key)) is not int or data[key] < 0 for key in keys):
        raise Refused("invalid_jest_counts")
    if (data["numPassedTests"] == 0 or not isinstance(data.get("success"), bool) or
            data["numTotalTests"] != sum(data[key] for key in keys[1:4])):
        raise Refused("no_executed_tests_or_inconsistent_jest_report")
    return {"tests": data["numTotalTests"], "passed": data["numPassedTests"],
            "failures": data["numFailedTests"], "failedSuites": data["numFailedTestSuites"],
            "skipped": data["numPendingTests"], "suites": data["numTotalTestSuites"],
            "success": data["success"]}


def verify_npm_cache(root: Path, cache: Path) -> dict:
    lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    installed = json.loads((cache / ".package-lock.json").read_text(encoding="utf-8"))
    expected, actual = lock["packages"], installed["packages"]
    for name, value in expected.items():
        if not name:
            continue
        if name not in actual:
            if value.get("optional") is True:
                continue
            raise Refused("required_dependency_missing")
        if any(value.get(key) != actual[name].get(key) for key in ("version", "resolved", "integrity")):
            raise Refused("dependency_lock_mismatch")
        if not (cache.parent / name).is_dir():
            raise Refused("dependency_directory_missing")
    if set(actual) - set(expected):
        raise Refused("unlocked_installed_dependency")
    return {"lockSha256": hashlib.sha256((root / "frontend/package-lock.json").read_bytes()).hexdigest(),
            "installedManifestSha256": hashlib.sha256((cache / ".package-lock.json").read_bytes()).hexdigest(),
            "installedPackages": len(actual), "optionalPackagesAbsent": len(set(expected) - set(actual) - {""}),
            "contentIntegrityAttested": False}


def same_component(root: Path, sha: str, paths: list[str]) -> None:
    # Include staged changes and unexpected source files, not only unstaged diff.
    if git(root, "diff", sha, "--", *paths) or git(root, "ls-files", "--others", "--exclude-standard", "--", *paths):
        raise Refused("component_source_changed")
    # NTFS incidents can replace bytes without changing Git's cached stat tuple.
    # Hash actual file content with Git's own newline/filter conversion every time.
    entries = git(root, "ls-tree", "-r", "-z", sha, "--", *paths).split("\0")
    files, expected = [], []
    for entry in entries:
        if not entry:
            continue
        metadata, name = entry.split("\t", 1)
        mode, kind, blob = metadata.split()
        if mode not in {"100644", "100755"} or kind != "blob":
            raise Refused("component_source_not_regular")
        file = root / name
        if not file.is_file() or file.is_symlink() or os.name == "nt" and file.is_junction():
            raise Refused("component_source_not_regular")
        files.append(name)
        expected.append(blob)
    if not files:
        raise Refused("component_source_missing")
    result = subprocess.run(["git", "hash-object", "--stdin-paths"], cwd=root,
                            input="\n".join(json.dumps(p, ensure_ascii=False) for p in files) + "\n",
                            capture_output=True, text=True, encoding="utf-8", timeout=60)
    if result.returncode or result.stdout.splitlines() != expected:
        raise Refused("component_content_mismatch")


def cleanup_android_outputs(directory: Path, data: dict) -> dict:
    """Discard only this marked run's derived outputs, after preserving its reports."""
    if (not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", directory.name) or
            data.get("schemaVersion") != 1 or data.get("runId") != directory.name or
            data.get("workflowMode") != "maintainer-local-executor" or
            data.get("state") not in {"success", "failure", "error"} or
            "android" not in data.get("profiles", {})):
        raise Refused("android_output_marker_mismatch")
    root = directory.resolve(strict=True)
    if os.name == "nt":
        text = str(root)
        # Gradle generates deeply nested Hilt/KSP names beyond MAX_PATH.
        # Use the Windows extended path for inspection and deletion alike.
        if not text.startswith("\\\\?\\"):
            directory = Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)
            root = directory.resolve(strict=True)
    targets = [directory / name for name in ("android-build", "gradle-project-cache")
               if (directory / name).exists() or (directory / name).is_symlink()]
    # Validate the whole deletion set before touching any target. No redirects,
    # junctions or other reparse points may reach the source or shared cache.
    for target in targets:
        if (target.is_symlink() or (os.name == "nt" and target.is_junction()) or
                not target.is_dir() or not target.resolve(strict=True).is_relative_to(root)):
            raise Refused("android_output_redirected")
        for parent, dirs, files in os.walk(target, followlinks=False):
            for name in dirs + files:
                child = Path(parent) / name
                if (child.is_symlink() or (os.name == "nt" and child.is_junction()) or
                        not child.resolve(strict=True).is_relative_to(root)):
                    raise Refused("android_output_redirected")
    # These final Gradle reports may include combined Debug and ordinary Release
    # variants. The separately recorded counts retain each invocation's meaning.
    reports = sorted((directory / "android-build/app/test-results").glob("*/TEST-*.xml"))
    if reports:
        import zipfile
        archive = directory / "android-final-junit.zip"
        if archive.is_symlink():
            raise Refused("android_report_redirected")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for report in reports:
                output.write(report, report.relative_to(directory / "android-build/app/test-results").as_posix())
    for target in targets:
        shutil.rmtree(target)
    return {"removedDirectories": [target.name for target in targets], "finalReportsArchived": bool(reports)}


def retain_runs(base: Path, *, keep: int = 10, byte_limit: int = 256 * 1024 * 1024) -> dict:
    """Prune only completed marked runs inside this executor's exact directory."""
    owned = []
    for directory in (base / "runs").glob("*"):
        if directory.is_symlink() or (os.name == "nt" and directory.is_junction()):
            raise Refused("run_directory_redirected")
        if not directory.is_dir() or not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", directory.name):
            raise Refused("unexpected_run_directory")
        marker = directory / "receipt.json"
        data = json.loads(marker.read_text(encoding="utf-8"))
        if (data.get("schemaVersion") != 1 or data.get("runId") != directory.name or
                data.get("workflowMode") != "maintainer-local-executor"):
            raise Refused("run_marker_mismatch")
        if data.get("state") != "running" and "android" in data.get("profiles", {}) and any(
                (directory / name).exists() for name in ("android-build", "gradle-project-cache")):
            cleanup = cleanup_android_outputs(directory, data)
            data["androidOutputCleanup"] = cleanup
            write_json(marker, data)
        files = list(directory.iterdir())
        if any(not file.is_file() or file.is_symlink() or
               (os.name == "nt" and file.is_junction()) for file in files):
            raise Refused("unexpected_run_contents")
        if data.get("state") == "running":
            raise Refused("previous_job_needs_reconciliation")
        owned.append((directory, sum(file.stat().st_size for file in files)))
    owned.sort(key=lambda row: row[0].name, reverse=True)
    removed, retained_bytes = [], 0
    for index, (directory, size) in enumerate(owned):
        if index < keep and retained_bytes + size <= byte_limit:
            retained_bytes += size
            continue
        target = directory.resolve(strict=True)
        if not target.is_relative_to((base / "runs").resolve(strict=True)):
            raise Refused("cleanup_path_outside_local_ci_runs")
        for file in directory.iterdir():
            file.unlink()  # Flat run files only; no recursive shell command.
        directory.rmdir()
        removed.append(directory.name)
    return {"retainedRuns": len(owned) - len(removed), "retainedBytes": retained_bytes,
            "removedRuns": removed, "maxRuns": keep, "maxBytes": byte_limit}


def link_cache(target: Path, source: Path) -> None:
    if target.exists() or target.is_symlink():
        raise Refused("cache_target_already_exists")
    if os.name == "nt":
        env = dict(os.environ, SPHERE_CI_LINK=str(target), SPHERE_CI_CACHE=str(source))
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:SPHERE_CI_LINK -Value $env:SPHERE_CI_CACHE | Out-Null"],
                       env=env, capture_output=True, check=True, timeout=15)
    else:
        target.symlink_to(source, target_is_directory=True)


@contextlib.contextmanager
def isolated_services(root: Path, run_id: str):
    """Disposable loopback PostgreSQL/Redis; no production credentials/volumes."""
    owned = []
    ports = {}
    images = {}
    try:
        for name, image, port in [("postgres", PG_IMAGE, 5432), ("redis", REDIS_IMAGE, 6379)]:
            candidates = [image, name + "@" + image.split("@", 1)[1]]
            if name == "postgres":
                # Explicit already-installed PG15 profile; never a mutable-tag fallback.
                # Its different binary is recorded, not claimed as the cloud PG digest.
                candidates.append(LOCAL_PG_IMAGE)
            for candidate in candidates:
                try:
                    metadata = json.loads(command(["docker", "image", "inspect", candidate], root))[0]
                    if metadata.get("Os") != "linux" or metadata.get("Architecture") != "amd64":
                        raise Refused("service_image_platform_mismatch")
                    image = candidate
                    images[name] = {"reference": image, "imageId": metadata["Id"],
                                    "matchesCloudReference": candidate.endswith("@" + candidates[0].split("@", 1)[1])}
                    break
                except Refused:
                    continue
            else:
                raise Refused("approved_cached_service_image_unavailable")
            args = ["docker", "create", "--pull=never", "--name", f"sphere-local-ci-{run_id}-{name}",
                    "--label", f"io.sphere.local-ci={run_id}", "--memory=512m", "--cpus=1",
                    "--log-driver=local", "--log-opt=max-size=10m", "--log-opt=max-file=2",
                    "--security-opt=no-new-privileges", "-p", f"127.0.0.1::{port}",
                    "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m"]
            if name == "postgres":
                args += ["--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev,size=256m",
                         "--tmpfs", "/var/run/postgresql:rw,nosuid,nodev,size=16m",
                         "-e", "POSTGRES_DB=sphereplatform_audit_ci", "-e", "POSTGRES_USER=sphere",
                         "-e", "POSTGRES_PASSWORD=test_password"]
            else:
                args += ["--tmpfs", "/data:rw,nosuid,nodev,size=32m"]
            container = command(args + [image], root)
            if not re.fullmatch(r"[0-9a-f]{64}", container):
                raise Refused("invalid_created_container_identity")
            owned.append(container)
            command(["docker", "start", container], root)
            deadline = time.monotonic() + 45
            while True:
                probe = ["pg_isready", "-U", "sphere"] if name == "postgres" else ["redis-cli", "ping"]
                try:
                    command(["docker", "exec", container, *probe], root, timeout=5)
                    break
                except Refused:
                    if time.monotonic() > deadline:
                        raise Refused("isolated_service_not_ready") from None
                    time.sleep(0.5)
            mapped = command(["docker", "port", container, f"{port}/tcp"], root)
            match = re.fullmatch(r"127\.0\.0\.1:([0-9]+)", mapped)
            if not match:
                raise Refused("isolated_service_not_loopback")
            ports[name] = int(match[1])
        yield {"POSTGRES_URL": f"postgresql+asyncpg://sphere:test_password@127.0.0.1:{ports['postgres']}/sphereplatform_audit_ci",
               "REDIS_URL": f"redis://127.0.0.1:{ports['redis']}/0", "SPHERE_RUN_INTEGRATION": "1",
               "SPHERE_AUDIT_REDIS_IMAGE": images["redis"]["reference"]}, images
    finally:
        for container in reversed(owned):
            label = command(["docker", "inspect", container, "--format", '{{index .Config.Labels "io.sphere.local-ci"}}'], root)
            if label != run_id:
                raise Refused("cleanup_container_ownership_mismatch")
            command(["docker", "rm", "-f", container], root)


def run_profile(root: Path, work: Path, run_dir: Path, profile: str, args, receipt: dict) -> dict:
    # Preserve a venv executable's path; resolving its symlink can bypass that venv.
    sha, python = receipt["source"]["sha"], str(Path(args.python).absolute())
    if not Path(python).is_file():
        raise Refused("python_executable_missing")
    env = child_environment(work, sha)
    result = {"state": "running", "startedAt": utc(), "steps": [], "packagingVerified": False}
    result_path = run_dir / f"{profile}.json"
    write_json(result_path, result)

    def step(label: str, argv: list[str], cwd: Path = work, extra: dict | None = None,
             timeout: int = 1200) -> None:
        observation = collect(root)
        raw_findings = evaluate(observation, min_ram_gib=12 if profile == "android" else 4)
        findings = admitted_findings(raw_findings,
            allow_degraded_volume=getattr(args, "allow_degraded_volume", False))
        if findings:
            raise Refused("resource_guard:" + ",".join(findings))
        print(json.dumps({"profile": profile, "step": label, "state": "started"}), flush=True)
        item = {"name": label, **run_step(argv, cwd, env | (extra or {}),
                run_dir / f"{profile}-{len(result['steps'])}.log", timeout=timeout)}
        item["resourcePreflight"] = observation | {"findings": raw_findings, "admissionFindings": findings}
        result["steps"].append(item)
        write_json(result_path, result)
        if item["exitCode"] != 0 or item["timedOut"]:
            raise Refused("step_failed:" + label)

    started = time.time()
    try:
        if profile == "frontend":
            node = str(Path(args.node).resolve(strict=True))
            result["nodeVersion"] = command([node, "--version"], root)
            if not re.fullmatch(r"v24\.[0-9]+\.[0-9]+", result["nodeVersion"]):
                raise Refused("node_24_required")
            env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
            cache = root / "frontend/node_modules"
            result["dependencies"] = verify_npm_cache(work, cache)
            link_cache(work / "frontend/node_modules", cache)
            step("action-contract", [python, "scripts/sync_action_contract.py", "--check"])
            step("jest", [node, str(cache / "jest/bin/jest.js"), "--ci", "--runInBand", "--json",
                          "--outputFile=" + str(run_dir / "jest.json")], work / "frontend")
            result["tests"] = jest_counts(run_dir / "jest.json", started)
            if not result["tests"]["success"] or result["tests"]["failures"] or result["tests"]["failedSuites"]:
                raise Refused("jest_test_failure")
            for file in ["test_preview_relay.cjs", "test_frontend_standalone_probe.mjs", "test_package_command_failure.mjs"]:
                step(file, [node, "--test", "tests/containers/" + file])
            step("archive-admission", [python, "-m", "unittest", "discover", "-s", "tests/containers",
                                       "-p", "test_*reviewed_web*.py"])
            step("types", [node, str(cache / "typescript/bin/tsc"), "--noEmit", "--incremental", "false"], work / "frontend")
            if verify_npm_cache(work, cache) != result["dependencies"]:
                raise Refused("dependency_cache_changed_during_test")
        elif profile == "backend":
            result["pythonVersion"] = command([python, "--version"], root)
            step("dependencies", [python, "-m", "pip", "check"])
            step("action-contract", [python, "scripts/sync_action_contract.py", "--check"])
            step("rls-policy", [python, "scripts/check_rls.py"])
            with isolated_services(root, run_dir.name) as (services, images):
                result["serviceImages"] = images
                step("fresh-migrations", [python, "-m", "alembic", "-c", "alembic/alembic.ini", "upgrade", "head"], extra=services)
                step("pytest-real-services", [python, "-m", "pytest", "tests/", "--ignore=tests/load", "-q", "--tb=short",
                     "--junitxml=" + str(run_dir / "backend-junit.xml"), "--cov=backend",
                     "--cov-report=xml:" + str(run_dir / "coverage.xml"), "--cov-fail-under=65"],
                     extra=services | {"COVERAGE_FILE": str(run_dir / ".coverage")})
                result["tests"] = junit_counts([run_dir / "backend-junit.xml"], started)
                if result["tests"]["failures"] or result["tests"]["errors"]:
                    raise Refused("pytest_test_failure")
                step("http-api-documentation", [python, "-m", "scripts.export_api_docs", "--check"], extra=services)
            result["isolatedServicesRemoved"] = True
        else:
            component_paths = ["android", "backend/schemas/action_contract.v1.json"]
            same_component(root, sha, component_paths)
            android = root / "android"
            env = child_environment(root, sha)
            env.update(JAVA_HOME=str(Path(args.java_home).resolve(strict=True)),
                       ANDROID_HOME=str(Path(args.android_home).resolve(strict=True)),
                       SPHERE_SERVER_URL="http://10.0.2.2:8000")
            result["javaVersion"] = command([str(Path(env["JAVA_HOME"]) / "bin" / ("java.exe" if os.name == "nt" else "java")), "--version"], root)
            gradle = str(android / ("gradlew.bat" if os.name == "nt" else "gradlew"))
            # Old output directories can be unreadable after a filesystem incident.
            # Never borrow old test reports/classes; keep every run's outputs private.
            output_base = run_dir / "android-build"
            init_script = run_dir / "android-output.gradle"
            init_script.write_text('allprojects { p -> p.layout.buildDirectory.set(new File(' +
                json.dumps(output_base.as_posix()) + ', p.name)) }\n', encoding="utf-8")
            flags = ["--offline", "--no-daemon", "--max-workers=2", "-Dorg.gradle.parallel=false",
                     "--init-script", str(init_script), "--project-cache-dir", str(run_dir / "gradle-project-cache"),
                     "--no-configuration-cache"]
            result["sourceMode"] = "verified-component-workspace-with-fresh-build-output"
            ordinary = [":app:testDevDebugUnitTest", ":app:testDevReleaseUnitTest",
                        ":app:testEnterpriseDebugUnitTest", ":app:testEnterpriseReleaseUnitTest"]
            clean_tests = [task.replace(":app:test", ":app:cleanTest") for task in ordinary]
            step("ordinary-all-unit-variants", [gradle, *flags, *clean_tests, *ordinary], android, timeout=2400)
            files = [p for task in ordinary for p in (output_base / "app/test-results" / task.split(":")[-1]).glob("TEST-*.xml")]
            result["ordinaryTests"] = junit_counts(files, started)
            canary_started = time.time()
            canary = {"SPHERE_DIRECT_TRANSPORT_CANARY": "true",
                      "SPHERE_DIRECT_PROBE_STUN_URL": "stun:stun.cloudflare.com:3478",
                      "SPHERE_STREAM_GPU_BRIDGE": "false", "SPHERE_STREAM_PLANAR_INPUT": "true",
                      "SPHERE_STREAM_GPU_PLANAR_INPUT": "true",
                      "SPHERE_CONTINUOUS_INPUT_CANARY": "true", "SPHERE_DEV_APPLICATION_ID_SUFFIX": ".pilot"}
            direct = [ordinary[0], ordinary[2]]
            step("direct-planar-continuous-unit-variants", [gradle, *flags,
                 *[task.replace(":app:test", ":app:cleanTest") for task in direct], *direct], android, canary, timeout=2400)
            files = [p for task in direct for p in (output_base / "app/test-results" / task.split(":")[-1]).glob("TEST-*.xml")]
            result["tests"] = junit_counts(files, canary_started)
            for counts in [result["tests"], result["ordinaryTests"]]:
                if counts["failures"] or counts["errors"]:
                    raise Refused("android_test_failure")
            same_component(root, sha, component_paths)
            result["apkInstalled"] = False
        if git(work, "diff", "--exit-code", "HEAD"):
            raise Refused("checkout_changed_during_tests")
        result["state"] = "success"
    except (Refused, OSError, ValueError, subprocess.SubprocessError, ET.ParseError) as error:
        result["state"] = "failure" if isinstance(error, Refused) and str(error).startswith("step_failed:") else "error"
        result["reason"] = str(error) if isinstance(error, Refused) else type(error).__name__
        # A nonzero test exit still has useful counts; never replace it with green.
        try:
            if profile == "backend" and (run_dir / "backend-junit.xml").exists():
                result["tests"] = junit_counts([run_dir / "backend-junit.xml"], started)
            elif profile == "frontend" and (run_dir / "jest.json").exists():
                result["tests"] = jest_counts(run_dir / "jest.json", started)
        except (Refused, OSError, ValueError, ET.ParseError):
            result["testCountsUnavailable"] = True
    except BaseException:
        result.update(state="error", reason="execution_interrupted")
        raise
    finally:
        result.update(finishedAt=utc(), elapsedSeconds=round(time.time() - started, 3))
        write_json(result_path, result)
    return result


def run(args) -> dict:
    root = Path(args.root).resolve(strict=True)
    source = validate_source(root, args.sha, args.trusted_ref)
    base = root / ".local-pilot/local-ci"
    base.mkdir(parents=True, exist_ok=True)
    if not base.resolve().is_relative_to(root):
        raise Refused("executor_storage_outside_workspace")
    with execution_lock(base / "execution.lock"):
        retention = retain_runs(base)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = base / "runs" / run_id
        run_dir.mkdir(parents=True)
        work = base / "workspaces" / run_id
        work.parent.mkdir(parents=True, exist_ok=True)
        receipt = {"schemaVersion": 1, "runId": run_id, "startedAt": utc(), "state": "running",
                   "source": source, "executorSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "profiles": {}, "rawLogsUploaded": False, "productionPackagingAccepted": False,
                   "publicForkJobsAccepted": False, "workflowMode": "maintainer-local-executor"}
        receipt["volumeExceptionRequested"] = getattr(args, "allow_degraded_volume", False)
        receipt["retentionBeforeRun"] = retention
        write_json(run_dir / "receipt.json", receipt)
        try:
            observation = collect(root)
            findings = evaluate(observation)
            receipt["resourcePreflight"] = observation | {"findings": findings}
            write_json(run_dir / "receipt.json", receipt)
            if admitted_findings(findings, allow_degraded_volume=receipt["volumeExceptionRequested"]):
                raise Refused("resource_guard_before_checkout")
            git(root, "worktree", "add", "--detach", str(work), args.sha)
            for profile in args.profiles:
                pending = None
                if args.publish:
                    pending = publish(root, args.sha, profile, "pending", "Local trusted tests are running")
                try:
                    result = run_profile(root, work, run_dir, profile, args, receipt)
                except BaseException:
                    result = {"state": "error", "reason": "execution_interrupted"}
                    if pending:
                        result["github"] = publish(root, args.sha, profile, "error", "Local execution interrupted; no test success")
                    receipt["profiles"][profile] = result
                    raise
                if pending:
                    result["githubPending"] = pending
                if args.publish:
                    count = result.get("tests", {}).get("tests", "unknown")
                    try:
                        result["github"] = publish(root, args.sha, profile, result["state"],
                             f"{count} tests; local {result['state']}; packaging is separate", args.report_url)
                    except Refused as error:
                        result["publicationError"] = str(error)
                        result["state"] = "error"
                receipt["profiles"][profile] = result
                write_json(run_dir / "receipt.json", receipt)
        finally:
            cache_link = work / "frontend/node_modules"
            if cache_link.is_symlink():
                cache_link.unlink()
            elif os.name == "nt" and cache_link.is_junction():
                os.rmdir(cache_link)  # Junction only; never recurse into shared dependencies.
            # Resolve and verify every recursive removal target; source drift retains checkout.
            if work.exists() and work.resolve().is_relative_to((base / "workspaces").resolve()):
                if not git(work, "status", "--porcelain", "--untracked-files=no"):
                    git(root, "worktree", "remove", str(work))
                    receipt["checkoutRemoved"] = True
                else:
                    receipt["checkoutRemoved"] = False
            receipt["finishedAt"] = utc()
            receipt["state"] = "success" if len(receipt["profiles"]) == len(args.profiles) and all(
                item["state"] == "success" for item in receipt["profiles"].values()) else "error"
            write_json(run_dir / "receipt.json", receipt)
            receipt["retentionAfterRun"] = retain_runs(base)
            write_json(run_dir / "receipt.json", receipt)
        return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--trusted-ref", default="refs/heads/codex/enterprise-audit-20260905")
    parser.add_argument("--profiles", nargs="+", choices=list(CONTEXTS), default=list(CONTEXTS))
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--node", default=shutil.which("node"))
    parser.add_argument("--java-home", default=os.environ.get("JAVA_HOME"))
    parser.add_argument("--android-home", default=os.environ.get("ANDROID_HOME"))
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--report-url")
    parser.add_argument("--allow-degraded-volume", action="store_true",
                        help="Explicit operator exception for a measured volume warning only")
    args = parser.parse_args()
    if len(args.profiles) != len(set(args.profiles)):
        parser.error("Profiles must be unique")
    if "frontend" in args.profiles and not args.node:
        parser.error("--node requires an installed Node 24 executable")
    if "android" in args.profiles and (not args.java_home or not args.android_home):
        parser.error("Android requires --java-home and --android-home")
    try:
        receipt = run(args)
    except (Refused, OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({"state": "error", "reason": str(error) if isinstance(error, Refused) else type(error).__name__}))
        return 2
    print(json.dumps({"runId": receipt["runId"], "sha": args.sha, "state": receipt["state"],
                      "profiles": {key: value["state"] for key, value in receipt["profiles"].items()}}))
    return 0 if receipt["state"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
