"""Compare measured offline PnP probes on exactly the same query frames."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def compare(baseline, candidate, geometry):
    import numpy as np

    old, new = baseline["samples"], candidate["samples"]
    if [s["source_index"] for s in old] != [s["source_index"] for s in new] or len(old) == 0:
        raise ValueError("probe_frames_mismatch")
    cameras = geometry["cameras"]
    times = np.asarray([v["ticks_90k"] / 90000 for v in cameras], dtype=float)
    centers = np.asarray([v["center"] for v in cameras], dtype=float)
    if len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("probe_geometry_invalid")
    step = float(np.median(np.linalg.norm(np.diff(centers, axis=0), axis=1)))
    if not np.isfinite(step) or step <= 1e-8:
        raise ValueError("probe_geometry_invalid")
    samples = []
    for first, second in zip(old, new):
        if abs(first["seconds"] - second["seconds"]) > 1e-6:
            raise ValueError("probe_time_mismatch")
        expected = first["retrieved_views"]
        if expected != [item["view"] for item in second["candidates"]]:
            raise ValueError("probe_candidates_mismatch")
        classical = [first["views"][str(i)] for i in expected if str(i) in first["views"]]
        learned = second["candidates"]
        ok_old = any(v["pnp_passed"] for v in classical)
        classical_passed = [v for v in classical if v["pnp_passed"]]
        classical_best = (
            max(classical_passed, key=lambda v: v["inliers"]) if classical_passed else None
        )
        classical_ambiguous = bool(
            classical_best
            and any(
                v is not classical_best
                and v["inliers"] >= 0.75 * classical_best["inliers"]
                and np.linalg.norm(np.asarray(v["center"]) - np.asarray(classical_best["center"]))
                > step * 2
                for v in classical_passed
            )
        )
        passed = [v for v in learned if v["pnp_passed"]]
        reference = np.array([np.interp(second["seconds"], times, centers[:, i]) for i in range(3)])
        best = max(passed, key=lambda v: v["inliers"]) if passed else None
        ambiguous = bool(
            best
            and any(
                v is not best
                and v["inliers"] >= 0.75 * best["inliers"]
                and np.linalg.norm(np.asarray(v["center"]) - np.asarray(best["center"])) > step * 2
                for v in passed
            )
        )
        disagreement = (
            None
            if best is None
            else float(np.linalg.norm(np.asarray(best["center"]) - reference) / step)
        )
        samples.append(
            {
                "source_index": second["source_index"],
                "seconds": second["seconds"],
                "baseline_pnp": ok_old,
                "lightglue_pnp": bool(passed),
                "baseline_ambiguous": classical_ambiguous,
                "baseline_unambiguous_candidate": bool(classical_best) and not classical_ambiguous,
                "lightglue_ambiguous": ambiguous,
                "lightglue_unambiguous_candidate": bool(best) and not ambiguous,
                "lightglue_center": None if best is None else best["center"],
                "reference_disagreement_in_median_steps": disagreement,
                "feature_ms": second["feature_ms"],
                "matching_ms": sum(v["matching_ms"] for v in learned),
                "verify_ms": sum(v["verify_ms"] for v in learned),
            }
        )

    def percentiles(values):
        return (
            None
            if not values
            else {
                "p50": float(np.percentile(values, 50)),
                "p95": float(np.percentile(values, 95)),
                "max": float(max(values)),
            }
        )

    previous = None
    pair_count, discontinuity_count = 0, 0
    for sample in samples:
        sample["center_pair_discontinuity"] = None
        if not sample["lightglue_unambiguous_candidate"]:
            previous = None
            continue
        current = np.asarray(sample["lightglue_center"])
        if previous is not None:
            dt = sample["seconds"] - previous["seconds"]
            if 0 < dt <= 0.5:
                pair_count += 1
                is_jump = bool(
                    np.linalg.norm(current - previous["center"]) > step * 5 * max(dt, 0.2)
                )
                sample["center_pair_discontinuity"] = is_jump
                discontinuity_count += int(is_jump)
        previous = {"seconds": sample["seconds"], "center": current}
    return {
        "schema": "sphere-lightglue-sift-comparison-v1",
        "samples": samples,
        "classical_passes": sum(s["baseline_pnp"] for s in samples),
        "classical_ambiguous": sum(s["baseline_ambiguous"] for s in samples),
        "classical_unambiguous_candidates": sum(
            s["baseline_unambiguous_candidate"] for s in samples
        ),
        "lightglue_passes": sum(s["lightglue_pnp"] for s in samples),
        "lightglue_ambiguous": sum(s["lightglue_ambiguous"] for s in samples),
        "lightglue_unambiguous_candidates": sum(
            s["lightglue_unambiguous_candidate"] for s in samples
        ),
        "consecutive_center_pairs": pair_count,
        "center_pair_discontinuities": discontinuity_count,
        "sequence_gate_is_partial_diagnostic": True,
        "lightglue_disagreement_steps": percentiles(
            [
                s["reference_disagreement_in_median_steps"]
                for s in samples
                if s["reference_disagreement_in_median_steps"] is not None
            ]
        ),
        "feature_ms": percentiles([s["feature_ms"] for s in samples]),
        "matching_ms": percentiles([s["matching_ms"] for s in samples]),
        "feature_plus_match_verify_ms": percentiles(
            [s["feature_ms"] + s["matching_ms"] + s["verify_ms"] for s in samples]
        ),
        "ground_truth": False,
        "metric_scale": None,
        "independent_pass": False,
        "physical_actions": 0,
        "execution_qualified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "geometry", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    dest = Path(a.output)
    if dest.exists():
        raise FileExistsError(dest)
    docs = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in (a.baseline, a.candidate, a.geometry)
    ]
    result = compare(*docs)
    write_json(dest, result)
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
