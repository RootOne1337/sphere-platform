"""Refresh a published detail pack using verified RenderWare Bin Mesh materials."""

import argparse
import gzip
import hashlib
import io
import json
import shutil
import sqlite3
import struct
from collections import Counter
from importlib import import_module
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.ariane_geometry import (
    model_types,
    restore_split_materials,
    scene_parts,
)
from scripts.pilot.world_map_lab.build_detail_scene import mesh_file, model_parts
from scripts.pilot.world_map_lab.destination_detail import mesh_primitives
from scripts.pilot.world_map_lab.index_ariane_world import inventory
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter
from scripts.pilot.world_map_lab.render_ariane_world import Textures, terrain_materials


def surface_geometry(compressed):
    result = Counter()
    for vertices, uv, triangles, _ in mesh_primitives(gzip.decompress(compressed)):
        points = np.column_stack((vertices, uv))[triangles]
        result.update(row.tobytes() for row in points)
    return result


def needs_repair(blob, kind):
    parser = import_module("gtaLib.dff").dff()
    parser.load_memory(blob)
    for _, mesh in scene_parts(parser, kind):
        original = mesh.triangles
        if restore_split_materials(mesh).triangles is not original:
            return True
    return False


def repair(source, adapter, previous, output):
    geo = load_local_adapter(source, adapter)
    archives = source / "models/img"
    entries = geo.index_files([*sorted(archives.glob("br_models_*.img")), archives / "br_terrain_models.img"])
    types, packs = model_types(source), geo.definition_dicts(source)
    revision = inventory(source, "black-russia-ariane")["placement_revision"]
    output.mkdir()
    candidate = output / "detail-scene.tmp.sqlite"
    shutil.copyfile(previous / "detail-scene.sqlite", candidate)
    corrected = {}
    with sqlite3.connect(candidate) as db:
        meta = json.loads(db.execute("select value from meta").fetchone()[0])
        if meta["revision"] != revision:
            raise ValueError("detail pack revision differs from the source map")
        textures = Textures(source, geo, texture_size=meta["textureLimit"], pack_cache=12)

        def save(image):
            array = np.ascontiguousarray(image, dtype=np.uint8)
            key = hashlib.sha256(struct.pack("<II", *array.shape[:2]) + array.tobytes()).hexdigest()
            if not db.execute("select 1 from texture where key=?", (key,)).fetchone():
                out = io.BytesIO()
                Image.fromarray(array).save(out, format="PNG", compress_level=3)
                db.execute("insert into texture values (?, ?)", (key, out.getvalue()))
            return key, bool(array[..., 3].min() < 125)

        rows = db.execute("select id,name,triangles from model order by id").fetchall()
        for number, (model, name, faces) in enumerate(rows, 1):
            blob = geo.read_entry(entries, name + ".dff")
            if b"\x0e\x05\0\0" not in blob or not needs_repair(blob, types[name]):
                continue
            meshes = model_parts(blob, types[name], packs.get(name, ""), textures,
                                 terrain_materials(blob, include_tiling=True))
            packed, _, _, count = mesh_file(meshes, save)
            prior = db.execute("select glb from model where id=?", (model,)).fetchone()[0]
            if count != faces or surface_geometry(prior) != surface_geometry(packed):
                raise ValueError(f"repair changes triangles or UVs in {name}")
            db.execute("update model set glb=? where id=?", (packed, model))
            corrected[name] = {
                "triangles": faces,
                "primitivesBefore": len(mesh_primitives(gzip.decompress(prior))),
                "primitivesAfter": len(mesh_primitives(gzip.decompress(packed))),
            }
            print(number, name, corrected[name], flush=True)
        meta["binMeshMaterialRepairs"] = len(corrected)
        meta["textures"] = db.execute("select count(*) from texture").fetchone()[0]
        db.execute("update meta set value=?", (json.dumps(meta),))
    db.close()
    candidate.replace(output / "detail-scene.sqlite")
    report = {"placementRevision": revision, "modelsAudited": len(rows), "repaired": corrected}
    (output / "repair-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Audited", len(rows), "models and repaired", len(corrected), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("source", "adapter", "previous", "output"):
        parser.add_argument("--" + argument, type=Path, required=True)
    args = parser.parse_args()
    repair(args.source, args.adapter, args.previous, args.output)
