"""Experimental local plane candidates from recorded SfM. No road qualification.

Lower-image visibility, a near-horizontal normal and RANSAC support are necessary
heuristics, not semantic proof of ground, body calibration or obstacle clearance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from motor_worker.browser_teach import validate_browser
from scripts.pilot.preview_route_trace import validate_geometry
from scripts.pilot.resource_guard import collect, evaluate


def fit(geometry):
    import numpy as np

    points = np.asarray(geometry["points"], np.float64)[:, :3]
    cameras = geometry["cameras"]
    if (
        not 60 <= len(points) <= 100000
        or not 2 <= len(cameras) <= 256
        or not np.isfinite(points).all()
    ):
        raise ValueError("surface_candidate_budget")
    centers = np.asarray([c["center"] for c in cameras])
    step = float(np.median(np.linalg.norm(np.diff(centers, axis=0), axis=1)))
    if not 1e-6 < step < 1e6:
        raise ValueError("surface_candidate_trace_step")
    threshold = step * 0.08
    rng = np.random.default_rng(17)
    visible = []
    for c in cameras:
        a = np.asarray(c["camera_to_world"])
        local = (points - a[:, 3]) @ a[:, :3]
        k = c["intrinsics"]
        z = np.maximum(local[:, 2], 1e-9)
        x = k["fx"] * local[:, 0] / z + k["cx"]
        y = k["fy"] * local[:, 1] / z + k["cy"]
        visible.append(
            (local[:, 2] > step * 0.5)
            & (local[:, 2] < step * 15)
            & (x > k["width"] * 0.12)
            & (x < k["width"] * 0.88)
            & (y > k["height"] * 0.63)
            & (y < k["height"] * 0.97)
        )
    rows = []
    for at, c in enumerate(cameras):
        q = points[np.sum(visible[max(0, at - 2) : at + 3], axis=0) >= 2]
        a = np.asarray(c["camera_to_world"])
        up = -np.mean(
            [np.asarray(x["camera_to_world"])[:, 1] for x in cameras[max(0, at - 2) : at + 3]],
            axis=0,
        )
        if np.linalg.norm(up) < 0.5:
            rows.append(dict(ticks=c["ticks_90k"], candidates=len(q), accepted=False))
            continue
        up /= np.linalg.norm(up)
        row = dict(ticks=c["ticks_90k"], candidates=len(q), accepted=False)
        best = None
        if len(q) >= 60:
            for _ in range(600):
                first, second, third = q[rng.choice(len(q), 3, replace=False)]
                n = np.cross(second - first, third - first)
                norm = np.linalg.norm(n)
                if norm < 1e-8:
                    continue
                n /= norm
                if n @ up < 0:
                    n = -n
                if n @ up < 0.85:
                    continue
                offset = -n @ first
                height = n @ a[:, 3] + offset
                if not step * 0.4 < height < step * 4:
                    continue
                keep = np.abs(q @ n + offset) < threshold
                score = int(keep.sum())
                if best is None or score > best[0]:
                    best = (score, keep)
        if best is not None and best[0] >= 60 and best[0] / len(q) >= 0.15:
            score, keep = best
            mean = q[keep].mean(axis=0)
            n = np.linalg.svd(q[keep] - mean, full_matrices=False)[2][-1]
            if n @ up < 0:
                n = -n
            offset = -n @ mean
            height = n @ a[:, 3] + offset
            if n @ up >= 0.85 and step * 0.4 < height < step * 4:
                row.update(
                    accepted=True,
                    normal=n.tolist(),
                    offset=float(offset),
                    support=score,
                    heightUnits=float(height),
                    centerOnCandidatePlane=(a[:, 3] - height * n).tolist(),
                    medianResidual=float(np.median(np.abs(q[keep] @ n + offset))),
                )
        rows.append(row)
    return dict(
        scope="LOCAL_PLANE_CANDIDATES_NOT_NAVIGATION",
        seed=17,
        metricScaleKnown=False,
        cameraBodyCalibrated=False,
        occlusionsChecked=False,
        executionQualified=False,
        physicalActions=0,
        accepted=sum(r["accepted"] for r in rows),
        total=len(rows),
        rows=rows,
        step=step,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.geometry.stat().st_size > 32 * 1024**2:
        raise ValueError("surface_evidence_bound_or_existing_output")
    if evaluate(collect(Path.cwd()), min_ram_gib=12):
        raise ValueError("surface_resource_guard")
    raw = args.geometry.read_bytes()
    geometry = json.loads(raw)
    validate_geometry(geometry, validate_browser(args.capture))
    result = fit(geometry)
    result["geometrySha256"] = hashlib.sha256(raw).hexdigest()
    result["sourceManifestSha256"] = geometry["source_manifest_sha256"]
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
    print(
        json.dumps(
            {key: result[key] for key in ("scope", "accepted", "total", "executionQualified")}
        )
    )


if __name__ == "__main__":
    main()
