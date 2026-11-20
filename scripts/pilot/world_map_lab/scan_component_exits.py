"""Inspect multiple candidate exits of each failed component against source collisions."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.audit_world_navmesh import projected_area
from scripts.pilot.world_map_lab.inspect_failed_routes import vertices
from scripts.pilot.world_map_lab.survey_clearance import measure
from scripts.pilot.world_map_lab.world_navmesh import Network, spatial_index


def survey(p):
    review = json.loads((p / "fixed-pair-recheck.json").read_bytes())
    raw = np.memmap(p / "world-geometry.bin", mode="r", dtype="u1")
    with Network(p, "drive") as nav:
        bounds = nav.meta["bounds"]
    index, chunks = spatial_index(raw, bounds)
    out = []
    for mode in ("drive", "walk"):
        f = np.load(p / f"{mode}-faces.npz")["faces"]
        ar = sum(
            projected_area(f["xyz"][:, [0, j, j + 1]]) * (f["vertices"] > j + 1)
            for j in range(1, 5)
        )
        areas = np.bincount(f["group"], weights=ar)
        with Network(p, mode) as nav:
            groups = set()
            pairs_by_group = {}
            for i, row in enumerate(review[mode]["pairs"], 1):
                if row["after"] == "complete":
                    continue
                gs = [nav.component(row[k]) for k in ("start", "end")]
                print(mode, i, [(g, round(areas[g])) for g in gs], flush=True)
                groups.update(gs)
                for g in gs:
                    pairs_by_group.setdefault(g, []).append(i)
            main = int(areas.argmax())
            mv = vertices(f, main)
            tree = cKDTree(mv)
            for g in sorted(groups - {main}):
                v = vertices(f, g)
                ds, ii = tree.query(v)
                sites = []
                stats = []
                for i in np.argsort(ds):
                    if ds[i] > 80 or len(sites) >= 28:
                        break
                    a, b = v[i], mv[ii[i]]
                    mid = 0.5 * (a + b)
                    if any(np.linalg.norm(mid - s) < 5 for s in sites):
                        continue
                    sites.append(mid)
                    r = {"a": a.tolist(), "b": b.tolist(), "mode": mode}
                    q = measure(r, raw, index, chunks, (bounds[0], bounds[3]))
                    rr = q["profile"]
                    dz = max(
                        (abs(h["floor"] - h["referenceZ"]) if h["floor"] is not None else 1000)
                        for h in rr
                    )
                    road = sum(
                        h["road"] is not None and abs(h["road"] - h["referenceZ"]) < 0.5 for h in rr
                    )
                    stats.append(
                        dict(
                            **r,
                            d=round(float(ds[i]), 2),
                            body=q["bodyIntersections"],
                            dz=round(dz, 2),
                            road=road,
                        )
                    )
                out.append(
                    {
                        "mode": mode,
                        "group": g,
                        "pairs": pairs_by_group[g],
                        "area": areas[g],
                        "nearest": float(ds.min()),
                        "sites": stats,
                    }
                )
                print(
                    "nearest",
                    round(float(ds.min()), 2),
                    "eligible",
                    [
                        (s["a"], s["b"], s["d"])
                        for s in stats
                        if not s["body"] and s["dz"] < 0.4 and (mode == "walk" or s["road"] == 17)
                    ][:5],
                    flush=True,
                )
    (p / "alternate-crossings.json").write_text(json.dumps(out), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    survey(parser.parse_args().folder)
