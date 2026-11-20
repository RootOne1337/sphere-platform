"""Locate failed endpoints on their original mesh components and inspect source geometry."""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.audit_navmesh_gaps import source_hits
from scripts.pilot.world_map_lab.audit_world_navmesh import projected_area
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter
from scripts.pilot.world_map_lab.world_navmesh import Network, checksum


def vertices(faces, group):
    part = faces[faces["group"] == group]
    return np.unique(part["xyz"][np.arange(6) < part["vertices"][:, None]], axis=0)


def collect(base, adapter):
    pairs = json.loads((base / "fixed-pair-recheck.json").read_bytes())
    old = json.loads((base / "world-gap-review.json").read_bytes())
    sites = [
        {"id": f"G{i:02d}", "mode": "drive", "a": g["a"], "b": g["b"], "group": g["group"]}
        for i, g in enumerate(old, 1)
    ]
    failures = []
    components = {}
    for mode in ("drive", "walk"):
        with (
            Network(base, mode, adapter=adapter) as net,
            np.load(base / f"{mode}-faces.npz", allow_pickle=False) as cache,
        ):
            if str(cache["geometry"]) != net.meta["geometrySha256"]:
                raise ValueError("stale component cache")
            faces = cache["faces"]
            areas = sum(
                projected_area(faces["xyz"][:, [0, j, j + 1]]) * (faces["vertices"] > j + 1)
                for j in range(1, 5)
            )
            sizes = np.bincount(faces["group"], weights=areas)
            main = int(sizes.argmax())
            mainverts = vertices(faces, main)
            search = cKDTree(mainverts)
            components[mode] = {"main": main, "meshSha256": checksum(base / f"{mode}.nav.zip")}
            seen = set()
            for i, row in enumerate(pairs[mode]["pairs"], 1):
                if row["after"] == "complete":
                    continue
                sid = ("D" if mode == "drive" else "W") + f"{i:02d}"
                gs = [net.component(row[k]) for k in ("start", "end")]
                ends = [row["start"], row["end"]]
                failures.append(
                    {
                        "id": sid,
                        "mode": mode,
                        "points": ends,
                        "groups": gs,
                        "areas": [round(sizes[g], 1) for g in gs],
                    }
                )
                for group in gs:
                    if group == main or group in seen:
                        continue
                    seen.add(group)
                    vv = vertices(faces, group)
                    dd, ii = search.query(vv)
                    best = int(np.argmin(dd))
                    sites.append(
                        {
                            "id": f"{mode}-{group}",
                            "mode": mode,
                            "a": vv[best].tolist(),
                            "b": mainverts[ii[best]].tolist(),
                            "group": group,
                        }
                    )
            del search, faces, mainverts
    return {"sites": sites, "failures": failures, "components": components}


def run(base, output, source, adapter):
    review = collect(base, output / "ariane-nav.dll")
    xyz = []

    def sample(p):
        xyz.append(p)
        return len(xyz) - 1

    for row in review["failures"]:
        row["samples"] = [sample(p) for p in row["points"]]
    for site in review["sites"]:
        a, b = np.array(site["a"]), np.array(site["b"])
        site["samples"] = [sample((a + (b - a) * t).tolist()) for t in np.linspace(0, 1, 9)]
    points = np.asarray(xyz)
    raw = source_hits(source, load_local_adapter(source, adapter), points)
    review["rays"] = [
        {
            "xyz": p,
            "surfaces": sorted(set(tuple(h) for h in hits), key=lambda h: (abs(h[0] - p[2]), h))[
                :8
            ],
        }
        for p, hits in zip(xyz, raw, strict=True)
    ]
    (output / "inspection.json").write_text(json.dumps(review, indent=1), encoding="utf-8")


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__)
    for k in ("base", "output", "source", "adapter"):
        a.add_argument("--" + k, type=Path, required=True)
    q = a.parse_args()
    run(q.base, q.output, q.source, q.adapter)
