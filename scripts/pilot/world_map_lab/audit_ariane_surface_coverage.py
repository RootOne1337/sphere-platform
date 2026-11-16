"""Survey all flat source mesh materials in selected places before classifying navigation."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from struct import Struct

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import instance_parts, model_types
from scripts.pilot.world_map_lab.index_ariane_world import inventory
from scripts.pilot.world_map_lab.project_ariane_roads import (
    ROAD_MATERIAL,
    SURFACE_LAYERS,
    load_local_adapter,
)

COL_HEADER = Struct("<4sI22sH")
SURFACE_NAME_HINT = re.compile(
    r"(?:road|asf|asph|walk|curb|kerb|pave|bord|trass|bridg|pavem|zemla|sidewalk|pesh)", re.I
)
REGIONS = {
    "batyrevo": (1374.0, 2957.0, 1505.0, 3000.0),
    "arzamas_north": (-1034.0, 984.0, 1068.0, 2091.0),
    "nizhny": (-3035.0, -1680.0, 2140.0, 3139.0),
}


def in_region(placement, bounds):
    x, y, _ = placement.position
    left, right, bottom, top = bounds
    return left <= x <= right and bottom <= y <= top


def collision_names(folder, geometry):
    found = set()
    for path, offset, length in geometry.index_files(
        sorted(folder.glob("br_collision_*.img"))
    ).values():
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(length)
        position = 0
        while position + COL_HEADER.size <= len(data):
            tag, size, raw_name, _ = COL_HEADER.unpack_from(data, position)
            if tag not in {b"COLL", b"COL2", b"COL3", b"COL4"}:
                break
            end = position + 8 + size
            if end < position + COL_HEADER.size or end > len(data):
                raise ValueError("invalid collision record")
            found.add(raw_name.split(b"\0", 1)[0].decode("ascii").lower())
            position = end
    return found


def summarize_parts(blob, kind):
    groups = []
    for vertices, mesh in instance_parts(blob, kind):
        faces = np.asarray([(f.a, f.b, f.c, f.material) for f in mesh.triangles], dtype=np.intp)
        if not faces.size:
            continue
        names = [m.textures[0].name.lower() if m.textures else "" for m in mesh.materials]
        valid = (faces[:, 3] >= 0) & (faces[:, 3] < len(names))
        faces = faces[valid]
        normals = np.cross(
            vertices[faces[:, 1]] - vertices[faces[:, 0]],
            vertices[faces[:, 2]] - vertices[faces[:, 0]],
        )
        groups.append((normals, np.linalg.norm(normals, axis=1), np.asarray(names)[faces[:, 3]]))
    return groups


def audit(root, geometry_tools):
    geometry = load_local_adapter(root, geometry_tools)
    model_folder = root / "models/img"
    models = geometry.index_files(
        sorted(model_folder.glob("br_models_*.img")) + [model_folder / "br_terrain_models.img"]
    )
    collision = collision_names(model_folder, geometry)
    types = model_types(root)
    placements = list(geometry.active_exterior())
    by_name = defaultdict(list)
    coverage = Counter()
    summary = {name: Counter() for name in REGIONS}
    missing_collision = Counter()
    regions = {name: Counter() for name in REGIONS}
    for placement in placements:
        model = placement.name + ".dff"
        has_model = model in models
        has_col = placement.name in collision
        coverage["exterior"] += 1
        coverage["with_visual_model"] += has_model
        coverage["with_named_collision"] += has_col
        coverage["with_both"] += has_model and has_col
        if not has_col:
            missing_collision[placement.name] += 1
        for region, bounds in REGIONS.items():
            if in_region(placement, bounds):
                regions[region]["placements"] += 1
                regions[region]["with_visual_model"] += has_model
                regions[region]["with_named_collision"] += has_col
                if has_model:
                    by_name[model].append((region, placement))
    for name, _ in sorted(models.items(), key=lambda pair: pair[1][:2]):
        selected = by_name.get(name)
        if not selected:
            continue
        parts = summarize_parts(geometry.read_entry(models, name), types[name.removesuffix(".dff")])
        terrain = models[name][0].name == "br_terrain_models.img"
        for region, placement in selected:
            rotation = geometry.ariane_rotation(placement.quat)
            for normals, areas, materials in parts:
                z = np.abs(rotation.apply(normals)[:, 2])
                eligible = (z >= 0.82 * areas) & (areas > 1e-5)
                valid_names = materials[eligible]
                valid_area = z[eligible] * 0.5
                for material, area in zip(valid_names.tolist(), valid_area.tolist(), strict=True):
                    summary[region][material or "(untextured)"] += area
                    regions[region]["top_faces"] += 1
                    regions[region]["top_area_units2"] += area
                    if terrain:
                        regions[region]["terrain_override_area_units2"] += area
                    if ROAD_MATERIAL.fullmatch(material):
                        regions[region]["selected_overview_area_units2"] += area
    result = {}
    for region, counts in regions.items():
        inventories = summary[region].most_common()
        result[region] = {
            "bounds": REGIONS[region],
            "counts": dict(counts),
            "material_count": len(inventories),
            "projected_area_by_layer": {
                layer: sum(area for name, area in inventories if regex.fullmatch(name))
                for layer, (regex, _) in SURFACE_LAYERS.items()
            },
            "top_materials": inventories[:35],
            "out_of_filter_name_hints": [
                (name, area)
                for name, area in inventories
                if SURFACE_NAME_HINT.search(name) and not ROAD_MATERIAL.fullmatch(name)
            ][:35],
        }
    source_index = inventory(root.resolve(strict=True), "black-russia-ariane")
    if source_index["exterior_placements"] != coverage["exterior"]:
        raise ValueError("source adapter and active placement index disagree")
    return {
        "schema": "sphere.ariane-surface-coverage.v1",
        "worldId": source_index["world_id"],
        "placementRevision": source_index["placement_revision"],
        "extent": dict(coverage),
        "placements_without_named_collider": missing_collision.most_common(),
        "regions": result,
        "scope": "Region membership uses placement origins. Triangle areas may overlap or reach outside region bounds. Names indicate materials, not clearance or connectivity.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--geometry-tools", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.source, args.geometry_tools)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "extent": report["extent"],
                "regions": {
                    name: {
                        "counts": entry["counts"],
                        "material_count": entry["material_count"],
                        "out_of_filter_name_hints": entry["out_of_filter_name_hints"][:12],
                    }
                    for name, entry in report["regions"].items()
                },
            }
        )
    )


if __name__ == "__main__":
    main()
