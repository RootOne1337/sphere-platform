"""Offline candidate-budget audit from an already completed LightGlue probe.

Times exclude candidate retrieval, data transfer, transport and input. A missed
conflict is measured relative to the complete recorded candidate set only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def analyze(report, geometry):
    import numpy as np

    samples = report["samples"]
    if (
        not samples
        or report.get("independent_pass") is not False
        or report.get("physical_actions") != 0
    ):
        raise ValueError("candidate_budget_scope_invalid")
    xyz = np.asarray([c["center"] for c in geometry["cameras"]], dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 2 or not np.isfinite(xyz).all():
        raise ValueError("candidate_budget_geometry_invalid")
    step = float(np.median(np.linalg.norm(np.diff(xyz, axis=0), axis=1)))
    if not np.isfinite(step) or step <= 1e-8:
        raise ValueError("candidate_budget_geometry_invalid")
    budgets = []

    def evaluate(candidates):
        passed = [c for c in candidates if c["pnp_passed"]]
        best = max(passed, key=lambda c: c["inliers"]) if passed else None
        conflict = bool(
            best
            and any(
                c is not best
                and c["inliers"] >= 0.75 * best["inliers"]
                and np.linalg.norm(np.asarray(c["center"]) - np.asarray(best["center"])) > 2 * step
                for c in passed
            )
        )
        return bool(passed), conflict

    for limit in range(1, 6):
        passed = conflicts = hidden = 0
        durations = []
        for sample in samples:
            candidates = sample["candidates"]
            if len(candidates) > 5:
                raise ValueError("candidate_budget_count_invalid")
            found, conflict = evaluate(candidates[:limit])
            _, full_conflict = evaluate(candidates)
            passed += found
            conflicts += conflict
            hidden += bool(found and not conflict and full_conflict)
            durations.append(
                sample["feature_ms"]
                + sum(c["matching_ms"] + c["verify_ms"] for c in candidates[:limit])
            )
        budgets.append(
            {
                "candidate_limit": limit,
                "pnp_passed": passed,
                "conflicts": conflicts,
                "no_conflict_among_tested": passed - conflicts,
                "conflicts_hidden_vs_recorded_set": hidden,
                "compute_ms_p50": float(np.percentile(durations, 50)),
                "compute_ms_p95": float(np.percentile(durations, 95)),
            }
        )
    return {
        "schema": "sphere-pnp-candidate-budget-audit-v1",
        "samples": len(samples),
        "budgets": budgets,
        "sample_origin": "same_recorded_video",
        "full_candidate_set_exhaustive": False,
        "independent_pass": False,
        "physical_actions": 0,
        "execution_qualified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "geometry", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    output = Path(a.output)
    if output.exists():
        raise FileExistsError(output)
    result = analyze(
        json.loads(Path(a.report).read_text(encoding="utf-8")),
        json.loads(Path(a.geometry).read_text(encoding="utf-8")),
    )
    write_json(output, result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
