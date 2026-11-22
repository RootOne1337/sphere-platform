"""Project road-material triangles from the active Ariane source into a whole-map overview."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from importlib import import_module
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.ariane_geometry import REGIONS, instance_parts, model_types
from scripts.pilot.world_map_lab.index_ariane_world import inventory

# This is a material survey. Direction, connectivity, and collision clearance are checked separately.
ROAD_MATERIAL = re.compile(
    r"(?:t_nn_road_[abcd](?:_[1-4])?|t_nn_roada_[ab]|t_lnd_asphalt[a-z0-9_]*|"
    r"t_asphalt[a-z0-9_]*|a889_newroad[0-9]+|r3_(?:dirtroad|roadcountry|newasphalt|oldasphalt)[a-z0-9_]*|"
    r"road_2_2_wt_lines|road_by_ank_[0-9]+|arz_road_clear[a-z0-9_]*|country_road[0-9]+|village_road|"
    # Verified at road-surface samples in the northeast and southeast.
    r"nbt_rd[5679]|t_asph_drt_lin[ab]|lf_arzrd[1-9]|lf_newrd[13]|"
    r"t_asphlt_notrcs_d(?:_alb)?|t_asph_d_(?:linb|dira)|crb_roadsv1(?:str2?)?|"
    r"crbroads66[467]|wolv_roads(?:cr4|_cross)|wolv_dr_(?:2|0b)|road_sel23_[12]|"
    r"reshnaaspha2|arz_per_2|lf_arzper2|zebr5323|t_nn_road_[yz]|srd_terrpick_road[23]?|sv_asph2|dt_road2|sber_road2_a889)"
)
# Kept as distinct visual hypotheses until collider, height and access checks.
ADDITIONAL_PAVEMENT = re.compile(
    r"(?:asfcrbtraskc[0-9][a-z0-9]*|perroad_[a-z0-9_]+|znam_asfalt|gso_perroad[0-9]+|"
    r"grnd_asphalt_mix|wolv_roads(?:_per)?|road_2_2|roadasf[0-9]+|"
    r"lf_arzasf[0-9]+|pikland_newasf[0-9]+|new_asf_center[0-9]+|"
    r"t_nn_dirtroad_[a-z]+|a889_dirtroad[0-9]+(?:_[234])?|ruscount_road[0-9]+|"
    r"road_sel(?:23(?:_end)?)?|svalka_road[12]|a889_dirtr[0-9]+|a889_sandroad1|"
    r"vad_dirtroad[67]|prich_dirtroad7|bys_sandyroad[23]|village_road2|"
    r"nbt_rd[123]_a889|auto_roadbet|park_road3|t_asphtransit_a|r3_roadsidetransita_c)"
)
PEDESTRIAN_MATERIAL = re.compile(
    r"(?:t_nn_pavem_[abcd]|pavement-small|pavementluk|t_nn_roadside_[ab]|"
    r"dc_sidewalk001|t_sidewalks_a|wolv_trot(?:[23]?_srd)?|lf_newpav[12]|"
    r"t_pav_slabs_[abd]_alb|a889_newtrop(?:3|4|7|8|9|14)|lf_arztropa1|"
    r"bys_sandytropa[1-4]|arz_trot_[23]|egorovkatropa2|"
    # Verified in the original Arzamas sidewalk and park models with their TXD materials.
    r"lf_arztrot[12]|arzpark_tile[234]|arzpark_brick[2567]|arzbrusch1|"
    r"srd_bruschatka2|rsn_ql_paving_0002)"
)
PIXELS_PER_UNIT = 0.35


def load_local_adapter(root, folder):
    """Reuse the previously checked RenderWare adapter and Ariane rotation."""
    sys.path.insert(0, str(folder))
    saved = sys.argv
    try:
        sys.argv = [saved[0], str(root)]
        return import_module("ariane_map")
    finally:
        sys.argv = saved
        sys.path.pop(0)


SURFACE_LAYERS = {
    "selected_road": (ROAD_MATERIAL, (177, 184, 83)),
    "additional_pavement": (ADDITIONAL_PAVEMENT, (103, 163, 221)),
    "pedestrian_candidates": (PEDESTRIAN_MATERIAL, (205, 154, 211)),
}


def surface_triangles(blob, kind):
    output = []
    for vertices, mesh in instance_parts(blob, kind):
        names = [item.textures[0].name.lower() if item.textures else "" for item in mesh.materials]
        for layer, (pattern, _) in SURFACE_LAYERS.items():
            matches = [bool(pattern.fullmatch(name)) for name in names]
            if not any(matches):
                continue
            hits = [
                (face.a, face.b, face.c, names[face.material])
                for face in mesh.triangles
                if 0 <= face.material < len(matches) and matches[face.material]
            ]
            if hits:
                indices = np.asarray([hit[:3] for hit in hits], dtype=np.intp)
                output.append((layer, vertices[indices], [hit[3] for hit in hits]))
    return output


def project(args):
    import cv2

    geometry = load_local_adapter(args.source, args.geometry_tools)
    index = json.loads(args.placement_index.read_bytes())
    current = inventory(args.source.resolve(strict=True), "black-russia-ariane")
    if json.dumps(index, sort_keys=True) != json.dumps(current, sort_keys=True):
        raise ValueError("outdated or modified placement index")
    size = index["tile_size_units"]
    occupied = [entry["tile"] for entry in index["tiles"]]
    left, right = min(x for x, _ in occupied) * size, (max(x for x, _ in occupied) + 1) * size
    bottom, top = min(y for _, y in occupied) * size, (max(y for _, y in occupied) + 1) * size
    if args.area:
        left, right, bottom, top = REGIONS[args.area]
    placement_bounds = {"left": left, "right": right, "bottom": bottom, "top": top}

    by_model = defaultdict(list)
    for placement in geometry.active_exterior():
        by_model[placement.name + ".dff"].append(placement)
    data = args.source / "models/img"
    model_files = sorted(data.glob("br_models_*.img")) + [data / "br_terrain_models.img"]
    entries = geometry.index_files(model_files)
    types = model_types(args.source)
    counts = Counter()
    batches = defaultdict(list)
    outlier_models = Counter()
    layer_faces = Counter()
    layer_materials = {layer: Counter() for layer in SURFACE_LAYERS}
    extent_min = np.full(2, np.inf)
    extent_max = np.full(2, -np.inf)
    for name, (archive, offset, _) in sorted(entries.items(), key=lambda item: item[1][:2]):
        placements = by_model.get(name)
        if not placements:
            continue
        blob = geometry.read_entry(entries, name)
        groups = surface_triangles(blob, types[name.removesuffix(".dff")])
        if not groups:
            continue
        counts["models_with_material"] += 1
        for placement in placements:
            rotation = geometry.ariane_rotation(placement.quat)
            touched = 0
            for layer, faces, materials in groups:
                points = (rotation.apply(faces.reshape(-1, 3)) + placement.position).reshape(
                    -1, 3, 3
                )
                flat = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
                area = np.linalg.norm(flat, axis=1)
                keep = (area > 1e-6) & (np.abs(flat[:, 2]) >= 0.82 * area)
                if args.area:
                    xy = points[:, :, :2]
                    keep &= (xy.max(axis=1) >= [left, bottom]).all(axis=1) & (
                        xy.min(axis=1) <= [right, top]
                    ).all(axis=1)
                if not keep.any():
                    continue
                xy = points[keep, :, :2]
                extent_min = np.minimum(extent_min, xy.min(axis=(0, 1)))
                extent_max = np.maximum(extent_max, xy.max(axis=(0, 1)))
                outside = (
                    (xy < [placement_bounds["left"], placement_bounds["bottom"]])
                    | (xy > [placement_bounds["right"], placement_bounds["top"]])
                ).any(axis=(1, 2))
                if outside.any():
                    outlier_models[name] += int(outside.sum())
                batches[layer].append(xy.astype(np.float32))
                layer_faces[layer] += len(xy)
                layer_materials[layer].update(materials[i] for i in np.flatnonzero(keep))
                touched += len(xy)
            if touched:
                counts["placed_surface_models"] += 1
                counts["faces"] += touched
        if counts["models_with_material"] % 250 == 0:
            print(dict(counts), flush=True)
    if not counts["faces"]:
        raise ValueError("the source did not resolve any selected surface geometry")
    if not args.area:
        left = min(left, math.floor(extent_min[0] / size) * size)
        right = max(right, math.ceil(extent_max[0] / size) * size)
        bottom = min(bottom, math.floor(extent_min[1] / size) * size)
        top = max(top, math.ceil(extent_max[1] / size) * size)
    if args.width:
        width = args.width
        height = math.ceil((top - bottom) * width / (right - left))
    else:
        scale = min(PIXELS_PER_UNIT, 4096 / max(right - left, top - bottom))
        width = math.ceil((right - left) * scale)
        height = math.ceil((top - bottom) * scale)
    background = np.full((height, width, 3), (29, 23, 16), dtype=np.uint8)

    def pixels(xy):
        return (xy - [left, top]) * [width / (right - left), -height / (top - bottom)]

    for entry in index["tiles"]:
        x, y = entry["tile"]
        a, b = np.rint(
            pixels(np.asarray([[x * size, (y + 1) * size], [(x + 1) * size, y * size]]))
        ).astype(int)
        intensity = min(29, int(5 * math.log2(1 + entry["placements"])))
        cv2.rectangle(
            background, tuple(a), tuple(b - 1), (32 + intensity, 30 + intensity, 19 + intensity), -1
        )

    surfaces = {}
    for layer in SURFACE_LAYERS:
        surface = np.zeros((height, width), dtype=np.uint8)
        for batch in batches[layer]:
            triangles = np.rint(pixels(batch)).astype(np.int32)
            for triangle in triangles:
                cv2.fillConvexPoly(surface, triangle, 255)
        surfaces[layer] = surface
    for layer, (_, color) in SURFACE_LAYERS.items():
        background[surfaces[layer] != 0] = color
    args.output.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output / "ariane-world-road-materials.png"), background):
        raise OSError("cannot write world overview")
    result = {
        "schema": "sphere.world-road-material-overview.v1",
        "worldId": index["world_id"],
        "placementRevision": index["placement_revision"],
        "bounds": {"left": left, "right": right, "bottom": bottom, "top": top},
        "placementBounds": placement_bounds,
        "area": args.area,
        "faces_extending_beyond_placement_bounds": outlier_models.total(),
        "models_extending_beyond_placement_bounds": outlier_models.most_common(30),
        "selectedTrianglesBounds": {
            "left": float(extent_min[0]),
            "right": float(extent_max[0]),
            "bottom": float(extent_min[1]),
            "top": float(extent_max[1]),
        },
        "imageWidth": width,
        "imageHeight": height,
        "imageSha256": hashlib.sha256(
            (args.output / "ariane-world-road-materials.png").read_bytes()
        ).hexdigest(),
        "geometry": dict(counts),
        "layers": {
            layer: {
                "faces": layer_faces[layer],
                "pixels": int(np.count_nonzero(surfaces[layer])),
                "materials": layer_materials[layer].most_common(),
            }
            for layer in SURFACE_LAYERS
        },
        "scope": "Visual material projections with overlap. Painted lanes, walkability, obstacles and connectivity require separate checks.",
    }
    (args.output / "ariane-world-road-materials.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k not in {"materials", "layers"}}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--geometry-tools", required=True, type=Path)
    parser.add_argument("--placement-index", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--area", choices=REGIONS)
    parser.add_argument("--width", type=int)
    args = parser.parse_args()
    if args.width is not None and not 320 <= args.width <= 4800:
        parser.error("--width must be between 320 and 4800")
    project(args)


if __name__ == "__main__":
    main()
