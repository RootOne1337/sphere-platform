"""Inventory road-related source materials and terrain masks across every exterior scene."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import instance_parts, model_types
from scripts.pilot.world_map_lab.index_ariane_world import inventory
from scripts.pilot.world_map_lab.project_ariane_roads import SURFACE_LAYERS, load_local_adapter
from scripts.pilot.world_map_lab.render_ariane_world import terrain_materials


def road_layer(name):
    return next(
        (layer for layer, (pattern, _) in SURFACE_LAYERS.items() if pattern.fullmatch(name)), None
    )


def digest_samples(placements):
    by_scene = Counter(item.scene for item in placements)
    first = placements[0]
    return {"scenes": dict(by_scene), "example": [first.scene, first.name, list(first.position)]}


def weight_by_material(vertices, faces):
    tri = vertices[faces[:, :3]]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    return normals, np.linalg.norm(normals, axis=1)


def entry_index(folder, geometry):
    return geometry.index_files(
        sorted(folder.glob("br_models_*.img")) + [folder / "br_terrain_models.img"]
    )


def survey(source, adapter):
    geometry = load_local_adapter(source, adapter)
    entries = entry_index(source / "models/img", geometry)
    by_model = defaultdict(list)
    for item in geometry.active_exterior():
        by_model[item.name + ".dff"].append(item)
    types = model_types(source)
    exposure = defaultdict(lambda: {"projected_area": 0.0, "faces": 0, "samples": []})
    masks = defaultdict(Counter)
    splat_sets = Counter()
    seen = 0
    for name in sorted(by_model, key=lambda key: entries[key][:2]):
        items = by_model[name]
        blob = geometry.read_entry(entries, name)
        kind = types[name.removesuffix(".dff")]
        if b"\x20\x01\x00\x00" in blob:
            for layer_set in terrain_materials(blob):
                if len(layer_set) != 5:
                    continue
                for layer in set(layer_set[:4]):
                    if layer:
                        masks[layer].update(item.scene for item in items)
                splat_sets[layer_set[:4]] += len(items)
        regular = sum(abs(item.quat[0]) <= 0.05 and abs(item.quat[1]) <= 0.05 for item in items)
        rotated = [item for item in items if abs(item.quat[0]) > 0.05 or abs(item.quat[1]) > 0.05]
        for vertices, mesh in instance_parts(blob, kind):
            if not mesh.triangles or not mesh.materials:
                continue
            faces = np.asarray([(f.a, f.b, f.c, f.material) for f in mesh.triangles], np.intp)
            faces = faces[(faces[:, 3] >= 0) & (faces[:, 3] < len(mesh.materials))]
            if not faces.size:
                continue
            normals, areas = weight_by_material(vertices, faces)
            area_sum = np.zeros(len(mesh.materials), np.float64)
            face_sum = np.zeros(len(mesh.materials), np.int64)
            for mult, z in [
                (regular, normals[:, 2]),
                *((1, geometry.ariane_rotation(p.quat).apply(normals)[:, 2]) for p in rotated),
            ]:
                if mult == 0:
                    continue
                weight = np.abs(z)
                eligible = (areas > 1e-6) & (weight >= 0.82 * areas)
                mat = faces[eligible, 3]
                area_sum += (
                    mult
                    * 0.5
                    * np.bincount(mat, weights=weight[eligible], minlength=len(mesh.materials))
                )
                face_sum += mult * np.bincount(mat, minlength=len(mesh.materials))
            for i in np.flatnonzero(face_sum):
                material = mesh.materials[i]
                if not material.textures:
                    continue
                key = material.textures[0].name.lower()
                row = exposure[key]
                row["projected_area"] += area_sum[i]
                row["faces"] += int(face_sum[i])
                if len(row["samples"]) < 4:
                    row["samples"].append(digest_samples(items))
        seen += 1
        if seen % 1500 == 0:
            print(f"{seen} models surveyed", flush=True)
    source_index = inventory(source, "black-russia-ariane")
    return {
        "schema": "sphere.ariane-road-source-survey.v1",
        "worldId": source_index["world_id"],
        "placementRevision": source_index["placement_revision"],
        "models": seen,
        "placements": sum(map(len, by_model.values())),
        "direct_materials": {
            name: {"layer": road_layer(name), **values}
            for name, values in sorted(
                exposure.items(), key=lambda entry: -entry[1]["projected_area"]
            )
        },
        "terrain_layer_placements": {
            layer: dict(scenes) for layer, scenes in sorted(masks.items())
        },
        "terrain_layer_sets": [[list(names), count] for names, count in splat_sets.most_common()],
        "area_scope": "Projected area counts overlapping source triangles. Terrain layer presence is separate from spatial mask weights.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--geometry-tools", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = survey(args.source.resolve(strict=True), args.geometry_tools)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("models", "placements", "placementRevision")}))
    print(
        "materials",
        len(report["direct_materials"]),
        "terrain layers",
        len(report["terrain_layer_placements"]),
    )


if __name__ == "__main__":
    main()
