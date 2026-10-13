"""Bind an immutable artifact to its successful job, including partial CI reruns."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from scripts.pilot.reviewed_image_archive import require


def check_artifact_attempt(run: dict[str, Any], receipt: dict[str, Any],
                           runner: Callable[[list[str]], str]) -> None:
    """A rerun of a failed job does not rebuild successful jobs' artifacts.

    The caller must separately admit the latest complete successful workflow,
    repository and source. Never relabel the archive's original run attempt.
    """
    latest, original = run.get("run_attempt"), receipt.get("runAttempt")
    require(type(latest) is int and type(original) is int and 1 <= original <= latest,
            "GitHub artifact attempt mismatch")
    if latest == original:
        return
    payload = json.loads(runner(["gh", "api", "repos/RootOne1337/sphere-platform/actions/runs/"
                                f"{receipt['runId']}/attempts/{original}/jobs?per_page=100"]))
    require(isinstance(payload, dict), "Invalid original CI job inventory")
    jobs = payload.get("jobs")
    count = payload.get("total_count")
    require(isinstance(jobs, list) and type(count) is int and len(jobs) == count <= 100
            and all(isinstance(job, dict) for job in jobs), "Incomplete original CI job inventory")
    matches = [job for job in jobs if job.get("name") == "Production image bootstrap"]
    require(len(matches) == 1, "Original artifact job is ambiguous")
    job = matches[0]
    require(job.get("run_id") == receipt["runId"] and job.get("head_sha") == receipt["sourceRevision"]
            and job.get("run_attempt") == original and job.get("status") == "completed"
            and job.get("conclusion") == "success", "Original artifact job not admitted")
