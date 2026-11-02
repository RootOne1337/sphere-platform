"""Compare grouped PnP with the previous saved pose on known jump frames.

This is a pairwise offline diagnostic, not a sequential tracker or ground truth.
"""

import argparse
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json


def compare(groups, baseline, geometry):
    import numpy as np

    if (
        groups.get("same_capture") is not True
        or groups.get("physical_actions") != 0
        or baseline.get("independent_pass") is not False
        or baseline.get("physical_actions") != 0
    ):
        raise ValueError("covisibility_compare_scope_invalid")
    poses = baseline["samples"]
    pos = {r["source_index"]: i for i, r in enumerate(poses)}
    if len(pos) != len(poses):
        raise ValueError("covisibility_compare_duplicate_frames")
    xyz = np.asarray([c["center"] for c in geometry["cameras"]], dtype=float)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or len(xyz) < 2 or not np.isfinite(xyz).all():
        raise ValueError("covisibility_compare_geometry_invalid")
    step = float(np.median(np.linalg.norm(np.diff(xyz, axis=0), axis=1)))
    if not np.isfinite(step) or step <= 1e-8:
        raise ValueError("covisibility_compare_geometry_invalid")
    output = []
    seen = set()
    for row in groups["samples"]:
        key = row["source_index"]
        if key in seen or key not in pos or pos[key] < 1:
            raise ValueError("covisibility_compare_frame_invalid")
        seen.add(key)
        at = pos[key]
        current = poses[at]
        prev = poses[at - 1]
        dt = row["seconds"] - prev["seconds"]
        if (
            abs(row["seconds"] - current["seconds"]) > 0.001
            or not 0 < dt <= 0.5
            or current["center_pair_discontinuity"] is not True
            or prev["lightglue_unambiguous_candidate"] is not True
        ):
            raise ValueError("covisibility_compare_pair_invalid")
        good = [c for c in row["groups"] if c["pnp_passed"]]
        best = max(good, key=lambda c: c["inliers"]) if good else None
        distance = (
            None
            if best is None
            else float(
                np.linalg.norm(np.asarray(best["center"]) - np.asarray(prev["lightglue_center"]))
                / step
            )
        )
        limit = 5 * max(dt, 0.2)
        output.append(
            {
                "source_index": key,
                "seconds": row["seconds"],
                "group_pnp": bool(best),
                "distance_in_median_steps": distance,
                "limit_in_median_steps": limit,
                "within_motion_limit": None if distance is None else distance <= limit,
            }
        )
    return {
        "schema": "sphere-covisibility-jump-comparison-v1",
        "samples": output,
        "sample_count": len(output),
        "group_pnp_count": sum(s["group_pnp"] for s in output),
        "within_motion_limit_count": sum(s["within_motion_limit"] is True for s in output),
        "ground_truth": False,
        "pairwise_only": True,
        "metric_scale": None,
        "physical_actions": 0,
        "execution_qualified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("groups", "baseline", "geometry", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        raise FileExistsError(out)
    docs = [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in (a.groups, a.baseline, a.geometry)
    ]
    result = compare(*docs)
    write_json(out, result)
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}))


if __name__ == "__main__":
    main()
