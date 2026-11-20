"""Check ground under a mixed itinerary against the COL and IPL in the staged GTA area."""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.native_collisions import COL, COL_NAME
from scripts.pilot.world_map_lab.native_route import native_route
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter


def sample_path(path, step=0.25):
    points = [path[0]]
    for a, b in zip(path, path[1:]):
        count = max(1, math.ceil(math.dist(a, b) / step))
        points.extend(
            [[u + (v - u) * i / count for u, v in zip(a, b)] for i in range(1, count + 1)]
        )
    return np.asarray(points)


def inspect_surface(root, source, adapter):
    geometry = load_local_adapter(source, adapter)
    from gtaLib import col

    config = json.loads((root / "sphere-scenario.json").read_bytes())
    paths, _, route_hash = native_route(root / "sphere-route.json")
    if route_hash != config["routeSha256"]:
        raise ValueError("staged route changed")
    folder = root / "data/maps/sphere_native"
    index = geometry.index_files([folder / "brquarter.img"])
    file, offset, length = index[COL_NAME.decode()]
    with file.open("rb") as stream:
        stream.seek(offset)
        data = stream.read(length)
    meshes = {}
    pos = 0
    while any(data[pos : pos + 8]):
        tag, size, raw_name, ident = COL.unpack_from(data, pos)
        end = pos + size + 8
        name = raw_name.partition(b"\0")[0].decode("ascii").lower()
        if (
            tag not in (b"COLL", b"COL2", b"COL3")
            or config["models"].get(name) != ident
            or end > len(data)
            or size < 24
        ):
            raise ValueError("invalid staged collision " + name)
        reader = col.coll()
        reader.load_memory(data[pos:end])
        (model,) = reader.models
        if model.mesh_faces:
            faces = np.asarray([(f.a, f.c, f.b) for f in model.mesh_faces])
            meshes[name] = np.asarray(model.mesh_verts)[faces]
        pos = end
    if hashlib.sha256(data[:pos]).hexdigest() != config["streamedCollisionSha256"]:
        raise ValueError("staged collision changed")
    places, lods = geometry.read_scene(folder / "brquarter.ipl")
    tris = []
    for item in places:
        mesh = meshes.get(item.name)
        if item.area == 0 and item.ordinal not in lods and mesh is not None:
            rot = geometry.ariane_rotation(item.quat)
            tris.append(rot.apply(mesh.reshape(-1, 3)).reshape(-1, 3, 3) + item.position)
    triangles = np.concatenate(tris)
    a, b, c = triangles.transpose(1, 0, 2)
    u, v = b - a, c - a
    det = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
    upward = det > 1e-8
    a, u, v, det = (k[upward] for k in (a, u, v, det))
    points = [sample_path(p) for p in paths]
    size = 16
    tiles = defaultdict(list)
    for leg, pts in enumerate(points):
        for i, (x, y, _) in enumerate(pts):
            tiles[(math.floor(x / size), math.floor(y / size))].append((leg, i))
    top = triangles[upward, :, :2].max(axis=1)
    bottom = triangles[upward, :, :2].min(axis=1)
    errors = [np.full(len(p), np.inf) for p in points]
    for (tx, ty), positions in tiles.items():
        lo = np.array([tx, ty]) * size
        keep = np.all((top >= lo) & (bottom <= lo + size), axis=1)
        a0, du, dv, d = (val[keep] for val in (a, u, v, det))
        for leg, i in positions:
            x, y, z = points[leg][i]
            dx, dy = x - a0[:, 0], y - a0[:, 1]
            s = (dx * dv[:, 1] - dy * dv[:, 0]) / d
            t = (dy * du[:, 0] - dx * du[:, 1]) / d
            hits = (s >= -1e-7) & (t >= -1e-7) & (s + t <= 1 + 1e-7)
            if np.any(hits):
                errors[leg][i] = np.min(np.abs((a0[:, 2] + s * du[:, 2] + t * dv[:, 2])[hits] - z))
    legs = []
    for mode, pts, err in zip(("walk", "drive", "walk"), points, errors, strict=True):
        failed = np.flatnonzero(err > 0.45)
        legs.append(
            dict(
                mode=mode,
                samples=len(pts),
                supported=len(pts) - len(failed),
                maxHeightError=float(err.max()) if np.isfinite(err).all() else None,
                failedSamples=[{"index": int(i), "xyz": pts[i].tolist()} for i in failed],
            )
        )
    return dict(
        routeSha256=route_hash,
        collisionSha256=config["streamedCollisionSha256"],
        sampleInterval=0.25,
        heightTolerance=0.45,
        legs=legs,
        verifiedInGame=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staged", "source", "geometry-tools", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = inspect_surface(args.staged, args.source, args.geometry_tools)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(
        [
            (leg["mode"], leg["supported"], leg["samples"], leg["maxHeightError"])
            for leg in result["legs"]
        ]
    )
