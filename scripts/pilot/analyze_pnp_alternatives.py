"""Offline audit of motion-consistent PnP alternatives after observed jumps.

Uses previous *individually unambiguous* best candidate only for a pairwise
diagnostic. It is neither a tracker replay nor an autonomous-control gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def analyze(report, comparison, geometry):
    import numpy as np

    samples, states = report["samples"], comparison["samples"]
    if (
        not samples
        or len(samples) != len(states)
        or any(
            a["source_index"] != b["source_index"] or abs(a["seconds"] - b["seconds"]) > 1e-6
            for a, b in zip(samples, states)
        )
    ):
        raise ValueError("alternatives_sample_mismatch")
    centers = np.asarray([c["center"] for c in geometry["cameras"]], dtype=float)
    if (
        len(centers) < 2
        or centers.ndim != 2
        or centers.shape[1] != 3
        or not np.isfinite(centers).all()
    ):
        raise ValueError("alternatives_geometry_invalid")
    step = float(np.median(np.linalg.norm(np.diff(centers, axis=0), axis=1)))
    if not np.isfinite(step) or step <= 1e-8:
        raise ValueError("alternatives_geometry_invalid")
    previous = None
    findings = []
    for sample, state in zip(samples, states):
        valid = [c for c in sample["candidates"] if c["pnp_passed"]]
        if not valid or not state["lightglue_unambiguous_candidate"]:
            previous = None
            continue
        best = max(valid, key=lambda c: c["inliers"])
        current = np.asarray(best["center"], dtype=float)
        if previous is not None:
            dt = sample["seconds"] - previous["seconds"]
            if 0 < dt <= 0.5:
                limit = step * 5 * max(dt, 0.2)
                jump = float(np.linalg.norm(current - previous["center"]))
                if jump > limit:
                    eligible = [c for c in valid if c["inliers"] >= 0.75 * best["inliers"]]
                    nearby = [
                        c
                        for c in eligible
                        if np.linalg.norm(np.asarray(c["center"]) - previous["center"]) <= limit
                    ]
                    findings.append(
                        {
                            "source_index": sample["source_index"],
                            "seconds": sample["seconds"],
                            "jump_in_median_steps": jump / step,
                            "limit_in_median_steps": limit / step,
                            "strong_candidates": len(eligible),
                            "motion_consistent_strong_candidates": len(nearby),
                            "candidate_views": [c["view"] for c in nearby],
                        }
                    )
        previous = {"seconds": sample["seconds"], "center": current}
    return {
        "schema": "sphere-pnp-alternative-audit-v1",
        "jumps": findings,
        "jump_count": len(findings),
        "jumps_with_strong_alternative": sum(
            bool(x["motion_consistent_strong_candidates"]) for x in findings
        ),
        "median_step_units": step,
        "pairwise_only": True,
        "ground_truth": False,
        "independent_pass": False,
        "physical_actions": 0,
        "execution_qualified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("report", "comparison", "geometry", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    output = Path(a.output)
    if output.exists():
        raise FileExistsError(output)
    docs = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in (a.report, a.comparison, a.geometry)
    ]
    result = analyze(*docs)
    write_json(output, result)
    print(json.dumps({k: v for k, v in result.items() if k != "jumps"}))


if __name__ == "__main__":
    main()
