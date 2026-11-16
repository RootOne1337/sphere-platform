"""Sample one exterior footway layer against Ariane's local authored collision geometry."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from importlib import import_module
from pathlib import Path

import numpy as np
from scipy import ndimage

from scripts.pilot.world_map_lab.ariane_geometry import instance_parts, model_types
from scripts.pilot.world_map_lab.project_ariane_roads import (
    PEDESTRIAN_MATERIAL,
    load_local_adapter,
)

# Candidate parameters for this tile and the existing body volume in the local adapter.
MIN_CLEARANCE = 0.75


def audit(source, geometry_tools, collision):
    geometry = load_local_adapter(source, geometry_tools)
    sys.path.insert(0, str(geometry_tools))
    try:
        raster = import_module("scooter4_drivable")
    finally:
        sys.path.pop(0)
    region = np.asarray(raster.REGION)
    left, right, bottom, top = region
    step = raster.STEP
    width, height = round((right - left) / step), round((top - bottom) / step)
    data = source / "models/img"
    models = geometry.index_files(
        sorted(data.glob("br_models_*.img")) + [data / "br_terrain_models.img"]
    )
    types = model_types(source)
    surfaces = []
    for placement in geometry.active_exterior():
        x, y, _ = placement.position
        if not left - 100 < x < right + 100 or not bottom - 100 < y < top + 100:
            continue
        model = geometry.read_entry(models, placement.name + ".dff")
        rotation = geometry.ariane_rotation(placement.quat)
        for local, mesh in instance_parts(model, types[placement.name]):
            vertices = rotation.apply(local) + placement.position
            indexes = {
                i
                for i, material in enumerate(mesh.materials)
                if material.textures
                and PEDESTRIAN_MATERIAL.fullmatch(material.textures[0].name.lower())
            }
            faces = [(t.a, t.b, t.c) for t in mesh.triangles if t.material in indexes]
            if faces:
                surfaces.append(vertices[np.asarray(faces, dtype=np.intp)])
    triangles = np.concatenate(surfaces)
    visual_height = raster.road_grid(
        triangles, region, step, width, height, np.empty((0, 0)), False
    )
    with np.load(collision, allow_pickle=False) as collision_data:
        if not np.array_equal(collision_data["region"], region) or collision_data["step"] != step:
            raise ValueError("collision snapshot belongs to a different tile")
        collide = collision_data["tris"]
        ground = raster.road_grid(collide, region, step, width, height, visual_height, True)
        support = np.isfinite(ground)
        open_cells = support.copy()
        raster.blockers(
            ground.shape, ground, open_cells, collision_data["boxes"], collision_data["spheres"]
        )
    raster.triangle_blockers(collide, region, ground, open_cells, step)
    clearance = ndimage.distance_transform_edt(open_cells) * step
    candidates = clearance >= MIN_CLEARANCE
    groups, num_groups = ndimage.label(candidates)
    if num_groups == 0:
        raise ValueError("no supported and unobstructed footway cells in the selected tile")
    patch_sizes = np.bincount(groups[candidates])
    # Pick an example whose endpoints remain visible inside the map canvas.
    inset = round(15.0 / step)
    interior = groups[inset:-inset, inset:-inset]
    example_ids = interior[interior > 0]
    if example_ids.size < 2:
        raise ValueError("no interior footways available for the demonstration")
    example_id = int(np.argmax(np.bincount(example_ids)))
    rows, columns = np.nonzero(interior == example_id)
    example_points = np.column_stack(
        (left + (columns + inset + 0.5) * step, top - (rows + inset + 0.5) * step)
    )
    report = {
        "grid": {"width": width, "height": height, "step": step, "left": left, "top": top},
        "horizontal_clearance": MIN_CLEARANCE,
        "free_b64": base64.b64encode(candidates.astype("u1").tobytes()).decode("ascii"),
        "collisionSnapshotSha256": hashlib.sha256(collision.read_bytes()).hexdigest(),
        "source_faces": len(triangles),
        "visible_surface_cells": int(np.isfinite(visual_height).sum()),
        "collision_supported_cells": int(support.sum()),
        "passage_candidate_cells": int(candidates.sum()),
        "largest_neighbor_patch_cells": int(patch_sizes.max()),
        "example": [
            example_points[example_points[:, 1].argmin()].tolist(),
            example_points[example_points[:, 1].argmax()].tolist(),
        ],
        "scope": "One exposed level of the district tile. Cells are static geometry candidates; neighbor patches do not measure connected pedestrian reachability.",
    }
    return report, {"free": candidates, "clearance": clearance, "height": ground}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--geometry-tools", required=True, type=Path)
    parser.add_argument("--collision", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report, raster = audit(args.source, args.geometry_tools, args.collision)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ariane-kremlin-footways-grid.json").write_text(
        json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8"
    )
    np.savez_compressed(args.output / "ariane-kremlin-footways-grid.npz", **raster)
    print(json.dumps({k: v for k, v in report.items() if k != "free_b64"}))


if __name__ == "__main__":
    main()
