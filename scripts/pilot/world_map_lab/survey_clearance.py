"""Measure collision, water, material evidence and corridor obstructions on a source transect."""

import argparse
import json
import math
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from scripts.pilot.world_map_lab.world_navmesh import TILE, checksum, spatial_index


def clip(poly, axis, limit, sign):
    out = []
    for i, p in enumerate(poly):
        q = poly[(i + 1) % len(poly)]
        d = sign * (p[axis] - limit)
        e = sign * (q[axis] - limit)
        if d >= 0:
            out.append(p)
        if (d >= 0) != (e >= 0):
            out.append(p + (q - p) * (d / (d - e)))
    return out


def measure(row, data, index, chunks, origin=(-3072, 3584)):
    a, b = np.array(row["a"]), np.array(row["b"])
    length = np.linalg.norm((b - a)[:2])
    if length < 0.001:
        direction = np.array([1.0, 0.0])
        length = 0.0
    else:
        direction = (b - a)[:2] / length
    side = np.array([-direction[1], direction[0]])
    radius = 1.5 if row["mode"] == "drive" else 0.5
    height = 2 if row["mode"] == "drive" else 1.875
    lo = np.minimum(a, b) - radius - 1
    hi = np.maximum(a, b) + radius + 1
    selected = set()
    for tx in range(
        math.floor((lo[0] - origin[0]) / TILE), math.floor((hi[0] - origin[0]) / TILE) + 1
    ):
        for ty in range(
            math.floor((origin[1] - hi[1]) / TILE), math.floor((origin[1] - lo[1]) / TILE) + 1
        ):
            selected.update(index.get((tx, ty), ()))
    batch = []
    kinds = []
    for i in sorted(selected):
        off, n, k, zmin, zmax = chunks[i]
        if zmax < lo[2] - 3 or zmin > hi[2] + 12:
            continue
        t = np.ndarray((n, 3, 3), "<f4", data, off)
        mask = np.all(
            (t[:, :, :2].max(axis=1) >= lo[:2]) & (t[:, :, :2].min(axis=1) <= hi[:2]), axis=1
        )
        if mask.any():
            batch.extend(t[mask])
            kinds.extend([k] * int(mask.sum()))
    t = np.asarray(batch, dtype=float).reshape(-1, 3, 3)
    kinds = np.asarray(kinds)
    cross = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    normal = cross[:, 2] / np.maximum(1e-8, np.linalg.norm(cross, axis=1))
    ab = t[:, 1] - t[:, 0]
    ac = t[:, 2] - t[:, 0]
    det = cross[:, 2]
    prof = []
    for f in np.linspace(0, 1, 17) if length else (0,):
        p = a + (b - a) * f
        offset = p[:2] - t[:, 0, :2]
        u = (offset[:, 0] * ac[:, 1] - offset[:, 1] * ac[:, 0]) / np.where(abs(det) > 1e-7, det, 1)
        v = (ab[:, 0] * offset[:, 1] - ab[:, 1] * offset[:, 0]) / np.where(abs(det) > 1e-7, det, 1)
        inside = (abs(det) > 1e-7) & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1.0000001)
        z = t[:, 0, 2] + ab[:, 2] * u + ac[:, 2] * v

        def near(mask):
            values = z[inside & mask]
            return round(float(values[np.argmin(abs(values - p[2]))]), 3) if len(values) else None

        prof.append(
            {
                "referenceZ": round(float(p[2]), 3),
                "floor": near((kinds == 0) & (normal > 0.7)),
                "road": near(kinds == 3),
                "paving": near(kinds == 4),
                "footpath": near(kinds == 5),
                "water": near(kinds == 2),
            }
        )
    # Intersect each blocking face with the swept body above the nominal floor line.
    tilt = (b[2] - a[2]) / max(length, 1e-5) if length else 0
    delta = t[:, :, :2] - a[:2]
    sx = delta @ direction
    local = np.stack([sx, delta @ side, t[:, :, 2] - a[2] - sx * tilt], axis=2)
    bounds = [(-0.05, length + 0.05), (-radius, radius), (0.375, height)]
    mask = (kinds == 1) | ((kinds == 0) & (normal < 0.7))
    for dim, (low, high) in enumerate(bounds):
        mask &= (local[:, :, dim].max(axis=1) >= low) & (local[:, :, dim].min(axis=1) <= high)
    hits = []
    for i in np.flatnonzero(mask):
        poly = list(local[i])
        for dim, (low, high) in enumerate(bounds):
            poly = clip(poly, dim, low, 1)
            poly = clip(poly, dim, high, -1)
        if poly:
            arr = np.array(poly)
            hits.append(
                {
                    "kind": "primitive" if kinds[i] == 1 else "collision face",
                    "along": round(float(arr[:, 0].mean()), 2),
                    "from": round(float(arr[:, 0].min()), 2),
                    "to": round(float(arr[:, 0].max()), 2),
                    "height": round(float(arr[:, 2].max()), 2),
                }
            )
    return {
        "profile": prof,
        "bodyIntersections": len(hits),
        "blockingHeight": max((hit["height"] for hit in hits), default=0.0),
        "blockedFrom": min((hit["from"] for hit in hits), default=None),
        "blockedTo": max((hit["to"] for hit in hits), default=None),
        "firstIntersections": sorted(hits, key=lambda x: x["along"])[:6],
    }


def run(base, output):
    rev = json.loads((output / "inspection.json").read_bytes())
    geo = json.loads((base / "geometry.json").read_bytes())
    raw = base / "world-geometry.bin"
    if checksum(raw) != geo["geometrySha256"]:
        raise ValueError("geometry mismatch")
    with ZipFile(base / "drive.nav.zip") as z:
        bounds = json.loads(z.read("manifest.json"))["bounds"]
    data = np.memmap(raw, dtype="u1", mode="r")
    index, chunks = spatial_index(data, bounds)
    for s in rev["sites"]:
        s.update(measure(s, data, index, chunks, (bounds[0], bounds[3])))
    (output / "clearance.json").write_text(json.dumps(rev), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("base", "output"):
        p.add_argument("--" + k, type=Path, required=True)
    args = p.parse_args()
    run(args.base, args.output)
