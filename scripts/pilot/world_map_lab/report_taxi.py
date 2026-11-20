"""Publish taxi planning, closed-loop drives and sampled source geometry at failed approaches."""

import argparse
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.inspect_failed_routes import vertices
from scripts.pilot.world_map_lab.report_world_journey import inspect
from scripts.pilot.world_map_lab.survey_clearance import measure
from scripts.pilot.world_map_lab.world_navmesh import Network, checksum, spatial_index


def inspect_approaches(folder, pairs, adapter):
    failures = [
        row
        for row in pairs
        if row["mode"] == "taxi" and row["reason"] in ("no_walk_to_road", "no_road_to_goal")
    ]
    if not failures:
        return
    with np.load(folder / "taxi-transfers.npz") as index:
        reachable = np.unique(index["points"]["walk"])
    with np.load(folder / "walk-faces.npz") as mesh:
        faces = mesh["faces"]
    # Compare exits to vertices on walkable components with a known road transfer.
    eligible = np.isin(faces["group"], reachable)
    road_faces = faces[eligible]
    road_points = road_faces["xyz"][np.arange(6) < road_faces["vertices"][:, None]]
    tree = cKDTree(road_points)
    cache = {}
    raw = np.memmap(folder / "world-geometry.bin", mode="r", dtype="u1")
    with Network(folder, "walk", adapter=adapter) as walk:
        bounds = walk.meta["bounds"]
        bins, chunks = spatial_index(raw, bounds)
        for row in failures:
            endpoint = row["start"] if row["reason"] == "no_walk_to_road" else row["end"]
            group = walk.component(endpoint)
            if group not in cache:
                points = vertices(faces, group)
                distances, nearest = tree.query(points)
                samples = []
                mids = []
                for i in np.argsort(distances):
                    first, second = points[i], road_points[nearest[i]]
                    gap = float(distances[i])
                    if gap > 80 or len(samples) == 5:
                        break
                    mid = (first + second) / 2
                    if any(math.dist(mid, other) < 3 for other in mids):
                        continue
                    mids.append(mid)
                    query = {"a": first.tolist(), "b": second.tolist(), "mode": "walk"}
                    section = measure(query, raw, bins, chunks, (bounds[0], bounds[3]))
                    profile = section["profile"]
                    samples.append(
                        dict(
                            **query,
                            gap=gap,
                            bodyHits=section["bodyIntersections"],
                            unsupported=sum(
                                point["floor"] is None
                                or abs(point["floor"] - point["referenceZ"]) > 0.375
                                for point in profile
                            ),
                            submerged=sum(
                                point["water"] is not None and point["water"] > point["referenceZ"]
                                for point in profile
                            ),
                        )
                    )
                cache[group] = dict(
                    component=group, nearestVertices=float(min(distances)), samples=samples
                )
            row["geometry"] = cache[group]


def publish(folder, pairs_file, featured, attempts, adapter, trials=()):
    base = folder / "journey"
    cases = [json.loads(line) for line in pairs_file.read_bytes().splitlines()]
    inspect_approaches(folder, cases, adapter)
    primary, *others = [inspect(attempt)[0] for attempt in (featured, *attempts)]
    report = dict(
        revision=json.loads((base / "route.json").read_bytes())["revision"],
        meshes={name: checksum(folder / (name + ".nav.zip")) for name in ("drive", "walk")},
        featured=primary,
        attempts=[primary, *others],
        trials=[dict(**inspect(path)[0], title=title) for title, path in trials],
        pairs=cases,
    )
    temp = base / "taxi-report.json.tmp"
    temp.write_text(json.dumps(report, allow_nan=False), encoding="utf8")
    temp.replace(base / "taxi-report.json")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("folder", "pairs", "featured"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--attempts", type=Path, nargs="*", default=[])
    cli.add_argument("--adapter", type=Path)
    cli.add_argument("--trial", nargs=2, metavar=("TITLE", "RUN_DIR"), action="append", default=[])
    args = cli.parse_args()
    publish(
        args.folder,
        args.pairs,
        args.featured,
        args.attempts,
        args.adapter,
        [(title, Path(path)) for title, path in args.trial],
    )
