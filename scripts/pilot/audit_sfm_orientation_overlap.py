"""Compare aligned camera positions and orientations on the same recording.

Alignment uses only earlier camera centers. Differences are not ground-truth
pose errors or distances in meters and never authorize navigation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.compare_remapped_sfm_correspondences import fit_similarity


def audit(baseline, candidate, *, fit_start=25.0, fit_end=28.5, test_start=29.0):
    import numpy as np

    source = baseline.get("source_manifest_sha256")
    if (
        not isinstance(source, str)
        or not re.fullmatch(r"[0-9a-f]{64}", source)
        or source != candidate.get("source_manifest_sha256")
    ):
        raise ValueError("orientation_source_mismatch")

    def cameras(data):
        result = {}
        for c in data["cameras"]:
            if c["image"] in result:
                raise ValueError("orientation_duplicate_camera")
            pose = np.asarray(c["camera_to_world"], dtype=float)
            center = np.asarray(c["center"], dtype=float)
            if (
                pose.shape not in {(3, 4), (4, 4)}
                or center.shape != (3,)
                or not np.isfinite(pose).all()
                or not np.isfinite(center).all()
                or pose.shape == (4, 4)
                and not np.allclose(pose[3], [0, 0, 0, 1], atol=1e-6)
                or not np.allclose(pose[:3, 3], center, atol=1e-5)
                or not np.allclose(pose[:3, :3] @ pose[:3, :3].T, np.eye(3), atol=1e-4)
                or not np.isclose(np.linalg.det(pose[:3, :3]), 1.0, atol=1e-4)
            ):
                raise ValueError("orientation_camera_invalid")
            result[c["image"]] = {
                "ticks": c["ticks_90k"],
                "center": center,
                "rotation": pose[:3, :3],
            }
        return result

    a, b = cameras(baseline), cameras(candidate)
    names = sorted(a.keys() & b.keys(), key=lambda name: a[name]["ticks"])
    if any(a[n]["ticks"] != b[n]["ticks"] for n in names):
        raise ValueError("orientation_timestamp_mismatch")
    fit = [n for n in names if fit_start <= a[n]["ticks"] / 90000 < fit_end]
    held = [n for n in names if a[n]["ticks"] / 90000 >= test_start]
    if len(fit) < 4 or len(held) < 4:
        raise ValueError("orientation_insufficient_views")
    old = np.asarray([a[n]["center"] for n in fit])
    new = np.asarray([b[n]["center"] for n in fit])
    scale, R, t = fit_similarity(new, old)
    step = float(np.median(np.linalg.norm(np.diff(old, axis=0), axis=1)))
    if not np.isfinite(step) or step <= 1e-8:
        raise ValueError("orientation_degenerate_step")

    def collect(items):
        result = []
        for n in items:
            d = float(np.linalg.norm(scale * (R @ b[n]["center"]) + t - a[n]["center"]) / step)
            diff = a[n]["rotation"].T @ (R @ b[n]["rotation"])
            degrees = float(np.degrees(np.arccos(np.clip((np.trace(diff) - 1) / 2, -1, 1))))
            result.append(
                {
                    "image": n,
                    "seconds": a[n]["ticks"] / 90000,
                    "center_disagreement_steps": d,
                    "orientation_disagreement_degrees": degrees,
                }
            )
        return result

    fit_rows, test_rows = collect(fit), collect(held)

    def summary(rows, key):
        values = [r[key] for r in rows]
        return {
            "count": len(values),
            "median": float(np.median(values)),
            "p95": float(np.percentile(values, 95)),
            "max": float(max(values)),
        }

    return {
        "schema": "sphere-sfm-orientation-overlap-v1",
        "source_manifest_sha256": baseline["source_manifest_sha256"],
        "fit_window": [fit_start, fit_end],
        "test_start": test_start,
        "fitted_scale": float(scale),
        "baseline_step_units": step,
        "fit": {
            "centers": summary(fit_rows, "center_disagreement_steps"),
            "orientations": summary(fit_rows, "orientation_disagreement_degrees"),
        },
        "heldout": {
            "centers": summary(test_rows, "center_disagreement_steps"),
            "orientations": summary(test_rows, "orientation_disagreement_degrees"),
        },
        "fit_rows": fit_rows,
        "heldout_rows": test_rows,
        "same_recording": True,
        "ground_truth": False,
        "metric_scale": None,
        "physical_actions": 0,
        "execution_qualified": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "candidate", "output"):
        p.add_argument("--" + name, required=True)
    a = p.parse_args()
    paths = [Path(a.baseline), Path(a.candidate)]
    out = Path(a.output)
    if out.exists():
        raise FileExistsError(out)
    raw = [path.read_bytes() for path in paths]
    result = audit(*(json.loads(v) for v in raw))
    result["source_geometry_sha256"] = [hashlib.sha256(v).hexdigest() for v in raw]
    if [path.read_bytes() for path in paths] != raw:
        raise ValueError("orientation_source_changed")
    write_json(out, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ("fit_rows", "heldout_rows")}))


if __name__ == "__main__":
    main()
