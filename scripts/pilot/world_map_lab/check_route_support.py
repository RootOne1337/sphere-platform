"""Compare samples along planned paths with the heights of independent source collision faces."""

import argparse
import json
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.world_navmesh import TILE, Network, checksum, spatial_index


def support(points, folder, bounds):
    raw = np.memmap(folder / "world-geometry.bin", mode="r", dtype="u1")
    index, chunks = spatial_index(raw, bounds)
    groups = {}
    for j, p in enumerate(points):
        key = (int(np.floor((p[0] - bounds[0]) / TILE)), int(np.floor((bounds[3] - p[1]) / TILE)))
        groups.setdefault(key, []).append(j)
    errors = [None] * len(points)
    for key, rows in groups.items():
        batch = [
            np.ndarray((n, 3, 3), "<f4", raw, off)
            for i in index.get(key, ())
            for off, n, k, _, _ in [chunks[i]]
            if k == 0
        ]
        if not batch:
            continue
        tri = np.concatenate(batch).astype(float)
        a = tri[:, 0]
        u = tri[:, 1] - a
        v = tri[:, 2] - a
        cross = np.cross(u, v)
        det = cross[:, 2]
        up = det > 1e-6
        det = np.where(up, det, 1)
        for j in rows:
            p = points[j]
            d = p[:2] - a[:, :2]
            t = (d[:, 0] * v[:, 1] - d[:, 1] * v[:, 0]) / det
            s = (u[:, 0] * d[:, 1] - u[:, 1] * d[:, 0]) / det
            valid = up & (t >= -1e-6) & (s >= -1e-6) & (s + t <= 1.000001)
            if valid.any():
                errors[j] = float(abs((a[:, 2] + t * u[:, 2] + s * v[:, 2])[valid] - p[2]).min())
    return errors


def run(folder):
    cases = json.loads((folder / "fixed-pair-recheck.json").read_bytes())
    report = {}
    for m in ("drive", "walk"):
        with Network(folder, m) as net:
            points = []
            ids = []
            snaps = []
            for i, r in enumerate(cases[m]["pairs"], 1):
                if r["after"] != "complete":
                    continue
                path = np.array(net.route(r["start"], r["end"])["path"])
                if not len(path):
                    raise ValueError("accepted path unavailable")
                snaps.extend(
                    np.linalg.norm(
                        path[[0, -1], :2] - np.asarray([r["start"], r["end"]])[:, :2], axis=1
                    ).tolist()
                )
                cumul = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
                sampled = np.stack(
                    [np.interp(np.linspace(0, cumul[-1], 17), cumul, axis) for axis in path.T],
                    axis=1,
                )
                points.extend(sampled)
                ids.extend([i] * len(sampled))
            errors = support(points, folder, net.meta["bounds"])
            valid = [e for e in errors if e is not None]
            report[m] = {
                "mesh": checksum(folder / f"{m}.nav.zip"),
                "samples": len(points),
                "supported": len(valid),
                "withinHalf": sum(e <= 0.5 for e in valid),
                "heightP95": float(np.percentile(valid, 95)),
                "endpointXYMax": max(snaps),
                "exceptions": [
                    {"pair": i, "xyz": p.tolist(), "error": e}
                    for i, p, e in zip(ids, points, errors, strict=True)
                    if e is None or e > 0.5
                ],
            }
    (folder / "route-support.json").write_text(json.dumps(report), encoding="utf-8")
    for m, r in report.items():
        print(m, {k: v for k, v in r.items() if k != "exceptions"})


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument("--folder", type=Path, required=True)
    run(a.parse_args().folder)
