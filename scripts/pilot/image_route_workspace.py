"""One owned CPU child for optional, source-bound image-route diagnostics.

This workspace never starts Android input or grants navigation authority. It is
serial with reconstruction so that feature extraction cannot race dense work.
An interrupted intent is reported, never silently retried by status/restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".local-pilot/motor-worker-venv/Scripts/python.exe"
TERMINAL = {"ready", "failed", "cancelled", "unavailable"}
MAX_SECONDS = 185
MAX_LOG_BYTES = 4 * 1024**2


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("image_route_workspace_state_invalid")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("image_route_workspace_state_invalid")
    return value


def read_status(job):
    folder = Path(job) / "image-route-workspace"
    if not os.path.lexists(folder):
        return None
    try:
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("image_route_workspace_invalid")
        value = _read(folder / "state.json")
        phase = value.get("phase")
        if phase not in TERMINAL | {"running", "pending"}:
            raise ValueError("image_route_workspace_state_invalid")
        return {
            "phase": phase,
            "execution_qualified": False,
            **({"error": str(value["error"])[:80]} if value.get("error") else {}),
        }
    except (OSError, ValueError, TypeError):
        return {
            "phase": "failed",
            "error": "image_route_workspace_invalid",
            "execution_qualified": False,
        }


def settle_interrupted(job):
    """Called only at service startup; never restarts a previous worker."""
    status = read_status(job)
    if status and status["phase"] in {"pending", "running"}:
        # A child of the previous service can outlive its HTTP parent. Signal
        # its existing cooperative checkpoint before reporting interruption.
        (Path(job) / "image-route-workspace/CANCEL").touch(exist_ok=True)
        (Path(job) / "CANCEL").touch(exist_ok=True)
        write_json(
            Path(job) / "image-route-workspace/state.json",
            {"phase": "failed", "error": "image_route_service_restarted"},
        )


def _stop_owned(process, folder):
    (folder / "CANCEL").touch(exist_ok=True)
    for action, delay in ((None, 3), ("terminate", 2), ("kill", 2)):
        if process.poll() is not None:
            return
        try:
            if action:
                getattr(process, action)()
            process.wait(timeout=delay)
            return
        except subprocess.TimeoutExpired:
            continue


def run_optional(job, mask, *, check=lambda: None, python=None, clock=time.monotonic):
    """Prepare diagnostics once before SfM; return a bounded optional outcome.

    ``check`` belongs to the caller and may stop the reconstruction itself. All
    such exceptions propagate after releasing our own child. Missing optional
    tools, a failed image match or an already interrupted workspace do not stop
    independent SfM. Existing valid reviews are reused without replacement.
    """
    from scripts.pilot.image_route_review import read_image_route_review

    job = Path(job)
    if job.is_symlink() or job.resolve(strict=True) != job.absolute():
        raise ValueError("image_route_workspace_path")
    if mask not in {"none", "avatar", "game"}:
        raise ValueError("image_route_workspace_mask")
    if os.path.lexists(job / "image-route-review"):
        try:
            read_image_route_review(job)
            return {"phase": "ready", "reused": True, "execution_qualified": False}
        except (OSError, ValueError, TypeError):
            return {
                "phase": "failed",
                "error": "image_route_existing_review_invalid",
                "execution_qualified": False,
            }
    folder = job / "image-route-workspace"
    if os.path.lexists(folder):
        return read_status(job)
    folder.mkdir()
    source = job / "input/manifest.json"
    if source.is_symlink() or not source.is_file() or source.stat().st_size > 65536:
        write_json(
            folder / "state.json", {"phase": "failed", "error": "image_route_source_invalid"}
        )
        return read_status(job)
    manifest_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    check()
    with (folder / "intent.json").open("x", encoding="utf-8") as file:
        json.dump(
            {
                "schema": "sphere-image-route-intent-v1",
                "source_manifest_sha256": manifest_sha,
                "mask": mask,
                "maximum_seconds": MAX_SECONDS,
                "execution_qualified": False,
            },
            file,
        )
    write_json(folder / "state.json", {"phase": "pending"})
    interpreter = Path(python) if python is not None else PYTHON
    if interpreter.is_symlink() or not interpreter.is_file():
        write_json(
            folder / "state.json",
            {"phase": "unavailable", "error": "image_route_cpu_runtime_unavailable"},
        )
        return read_status(job)
    process = None
    caller_check_failed = False

    def caller_check():
        nonlocal caller_check_failed
        try:
            check()
        except BaseException:
            caller_check_failed = True
            raise

    began = clock()
    try:
        with (folder / "worker.log").open("xb") as log:
            process = subprocess.Popen(
                [
                    str(interpreter),
                    "-m",
                    "scripts.pilot.image_route_builder",
                    "--job",
                    str(job),
                    "--mask",
                    mask,
                ],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        write_json(folder / "state.json", {"phase": "running"})
        while process.poll() is None:
            caller_check()
            reason = (
                "cancelled"
                if (job / "CANCEL").exists() or (folder / "CANCEL").exists()
                else "image_route_worker_timeout"
                if clock() - began >= MAX_SECONDS
                else "image_route_log_quota"
                if (folder / "worker.log").stat().st_size > MAX_LOG_BYTES
                else None
            )
            if reason:
                _stop_owned(process, folder)
                write_json(
                    folder / "state.json",
                    {"phase": "cancelled" if reason == "cancelled" else "failed", "error": reason},
                )
                return read_status(job)
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
        caller_check()
        if (job / "CANCEL").exists() or (folder / "CANCEL").exists():
            write_json(
                folder / "state.json",
                {"phase": "cancelled", "error": "image_route_preparation_cancelled"},
            )
        elif (folder / "worker.log").stat().st_size > MAX_LOG_BYTES:
            write_json(folder / "state.json", {"phase": "failed", "error": "image_route_log_quota"})
        elif process.returncode != 0:
            write_json(
                folder / "state.json", {"phase": "failed", "error": "image_route_worker_failed"}
            )
        else:
            read_image_route_review(job)
            write_json(folder / "state.json", {"phase": "ready"})
        return read_status(job)
    except BaseException as error:
        if process is not None:
            _stop_owned(process, folder)
        write_json(
            folder / "state.json",
            {
                "phase": "cancelled" if str(error) == "cancelled" else "failed",
                "error": "image_route_preparation_interrupted",
            },
        )
        if caller_check_failed or not isinstance(error, Exception):
            raise
        return read_status(job)
