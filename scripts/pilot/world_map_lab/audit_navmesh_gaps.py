"""Find separated vehicle components and identify visual source faces between their nearest edges."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from scripts.pilot.world_map_lab.ariane_geometry import instance_parts, model_types
from scripts.pilot.world_map_lab.audit_world_navmesh import projected_area
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter


def gaps(faces):
    areas = sum(
        projected_area(faces["xyz"][:, [0, k, k + 1]]) * (faces["vertices"] > k + 1)
        for k in range(1, 5)
    )
    size = np.bincount(faces["group"], weights=areas)
    ordered = np.argsort(size)[::-1]

    def vertices(group):
        part = faces[faces["group"] == group]
        return np.unique(part["xyz"][np.arange(6) < part["vertices"][:, None]], axis=0)

    main = vertices(ordered[0])
    tree = cKDTree(main)
    output = []
    for group in ordered[1:12]:
        if size[group] <= 0:
            break
        candidates = vertices(group)
        distance, index = tree.query(candidates)
        sites = []
        for i in np.argsort(distance):
            if distance[i] > 100 or len(sites) >= 5:
                break
            a, b = candidates[i], main[index[i]]
            mid = (a + b) / 2
            if any(np.linalg.norm(mid[:2] - s[:2]) < 85 for s in sites):
                continue
            sites.append(mid)
            output.append(
                {
                    "group": int(group),
                    "groupArea": float(size[group]),
                    "a": a.tolist(),
                    "b": b.tolist(),
                    "gap": float(distance[i]),
                }
            )
    return output


def record_hits(vertices, mesh, queries, where, hits, model):
    low, high = vertices[:, :2].min(axis=0), vertices[:, :2].max(axis=0)
    where = where[((queries[where, :2] >= low) & (queries[where, :2] <= high)).all(axis=1)]
    if not len(where):
        return
    faces = np.asarray([(f.a, f.b, f.c, f.material) for f in mesh.triangles], np.intp)
    a, b, c = (vertices[faces[:, k]] for k in range(3))
    u, v = b - a, c - a
    det = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    valid = abs(det) > 1e-6
    det[~valid] = 1
    names = [m.textures[0].name.lower() if m.textures else "(no diffuse)" for m in mesh.materials]
    for j in where:
        delta = queries[j] - a
        s = (delta[:, 0] * v[:, 1] - delta[:, 1] * v[:, 0]) / det
        t = (u[:, 0] * delta[:, 1] - u[:, 1] * delta[:, 0]) / det
        for i in np.flatnonzero(valid & (s >= 0) & (t >= 0) & (s + t <= 1)):
            z = a[i, 2] + s[i] * u[i, 2] + t[i] * v[i, 2]
            mat = faces[i, 3]
            hits[j].append(
                [round(float(z), 3), names[mat] if 0 <= mat < len(names) else "(unknown)", model]
            )


def source_hits(source, geometry, queries):
    queries_xy = cKDTree(queries[:, :2])
    hits = [[] for _ in queries]
    by_name = defaultdict(list)
    for place in geometry.active_exterior():
        by_name[place.name].append(place)
    source_dir = source / "models/img"
    models = geometry.index_files(
        sorted(source_dir.glob("br_models_*.img")) + [source_dir / "br_terrain_models.img"]
    )
    types = model_types(source)
    for filename, _ in sorted(models.items(), key=lambda item: item[1][:2]):
        name = filename.removesuffix(".dff")
        places = by_name.get(name)
        if not places:
            continue
        for vertices, mesh in instance_parts(geometry.read_entry(models, filename), types[name]):
            if not len(vertices) or not mesh.triangles:
                continue
            radius = np.linalg.norm(vertices, axis=1).max() + 0.01
            for place in places:
                where = queries_xy.query_ball_point(place.position[:2], radius)
                if not where:
                    continue
                world = geometry.ariane_rotation(place.quat).apply(vertices) + place.position
                record_hits(world, mesh, queries, np.asarray(where), hits, model=name)
    return hits


def audit(source, adapter, folder):
    geometry = load_local_adapter(source, adapter)
    manifest = json.loads((folder / "geometry.json").read_bytes())
    with np.load(folder / "drive-faces.npz", allow_pickle=False) as cache:
        if str(cache["geometry"]) != manifest["geometrySha256"]:
            raise ValueError("obsolete mesh cache")
        rows = gaps(cache["faces"])
    if not rows:
        return rows
    queries = np.asarray(
        [
            np.asarray(r["a"]) * (1 - f) + np.asarray(r["b"]) * f
            for r in rows
            for f in (0.15, 0.5, 0.85)
        ]
    )
    hits = source_hits(source, geometry, queries)
    for i, row in enumerate(rows):
        row["samples"] = [
            {
                "xyz": queries[j].tolist(),
                "nearestSurfaces": [
                    h[:2] for h in sorted(hits[j], key=lambda s: abs(s[0] - queries[j, 2]))[:3]
                ],
            }
            for j in range(3 * i, 3 * i + 3)
        ]
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "geometry-tools", "folder"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    data = audit(args.source, args.geometry_tools, args.folder)
    (args.folder / "world-gap-review.json").write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )
    print("surveyed gaps", len(data))
