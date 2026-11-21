"""Compare camera centers of two SfM reconstructions using a held-out time span.

Fit 7-DoF similarity on common *earlier* camera centers, then report disagreement
on later held-out centers. Both share image features and are not independent
ground truth. Units are normalized by baseline median camera step, not metres.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def compare(
    baseline_path, candidate_path, output, *, fit_start=25.0, fit_end=28.5, test_start=29.0
):
    import numpy as np

    if output.exists():
        raise FileExistsError("comparison_output_exists")
    raw_a, raw_b = baseline_path.read_bytes(), candidate_path.read_bytes()
    a, b = json.loads(raw_a), json.loads(raw_b)
    if a["source_manifest_sha256"] != b["source_manifest_sha256"]:
        raise ValueError("comparison_source_mismatch")
    left = {c["image"]: c for c in a["cameras"]}
    right = {c["image"]: c for c in b["cameras"]}
    if len(left) != len(a["cameras"]) or len(right) != len(b["cameras"]):
        raise ValueError("comparison_duplicate_camera")
    names = sorted(left.keys() & right.keys(), key=lambda n: left[n]["ticks_90k"])
    if any(left[n]["ticks_90k"] != right[n]["ticks_90k"] for n in names):
        raise ValueError("comparison_timestamp_mismatch")
    fit = [n for n in names if fit_start <= left[n]["ticks_90k"] / 90000 < fit_end]
    held = [n for n in names if left[n]["ticks_90k"] / 90000 >= test_start]
    if len(fit) < 4 or len(held) < 4:
        raise ValueError("comparison_insufficient_views")
    x = np.asarray([right[n]["center"] for n in fit], float)
    y = np.asarray([left[n]["center"] for n in fit], float)
    mx, my = x.mean(axis=0), y.mean(axis=0)
    xc, yc = x - mx, y - my
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.linalg.matrix_rank(xc) < 2:
        raise ValueError("comparison_degenerate_alignment")
    u, s, vt = np.linalg.svd((xc.T @ yc) / len(x))
    sign = np.ones(3)
    if np.linalg.det(vt.T @ u.T) < 0:
        sign[-1] = -1
    rotation = vt.T @ np.diag(sign) @ u.T
    variance = float(np.sum(xc * xc) / len(x))
    scale = float(np.sum(s * sign) / variance)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("comparison_invalid_scale")
    translation = my - scale * (rotation @ mx)
    step = float(np.median(np.linalg.norm(np.diff(y, axis=0), axis=1)))
    if step <= 1e-9:
        raise ValueError("comparison_degenerate_reference_step")

    def rows(items):
        result = []
        for n in items:
            p = np.asarray(right[n]["center"], float)
            q = np.asarray(left[n]["center"], float)
            delta = float(np.linalg.norm(scale * (rotation @ p) + translation - q))
            result.append(
                dict(
                    image=n,
                    seconds=left[n]["ticks_90k"] / 90000,
                    disagreement_baseline_steps=delta / step,
                )
            )
        return result

    fit_rows, held_rows = rows(fit), rows(held)

    def stats(items):
        values = np.asarray([r["disagreement_baseline_steps"] for r in items])
        return dict(
            count=len(values),
            median=float(np.median(values)),
            p95=float(np.percentile(values, 95)),
            maximum=float(np.max(values)),
        )

    report = dict(
        schema="same-recording-sfm-overlap-comparison-v1",
        source_manifest_sha256=a["source_manifest_sha256"],
        baseline_geometry_sha256=hashlib.sha256(raw_a).hexdigest(),
        candidate_geometry_sha256=hashlib.sha256(raw_b).hexdigest(),
        same_recording=True,
        shared_feature_graph=True,
        independent_ground_truth=False,
        metric_scale_known=False,
        disagreement_is_not_error=True,
        fit_window=[fit_start, fit_end],
        test_start=test_start,
        fitted_scale=scale,
        baseline_step_units=step,
        fit=stats(fit_rows),
        heldout=stats(held_rows),
        fit_rows=fit_rows,
        heldout_rows=held_rows,
        physical_actions=0,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2, allow_nan=False)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("fit_rows", "heldout_rows")}, indent=2
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    compare(args.baseline, args.candidate, args.output)
