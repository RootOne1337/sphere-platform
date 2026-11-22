"""Pack original exterior model geometry once and index placements for on-demand street inspection."""

import argparse
import gzip
import hashlib
import io
import itertools
import json
import sqlite3
import struct
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.ariane_geometry import instance_parts, model_types
from scripts.pilot.world_map_lab.index_ariane_world import inventory
from scripts.pilot.world_map_lab.project_ariane_roads import load_local_adapter
from scripts.pilot.world_map_lab.render_ariane_world import Textures, terrain_materials


def aligned(blob, pad):
    return blob + pad * (-len(blob) % 4)


def mesh_file(parts, texture):
    payload = bytearray()
    views = []
    accessors = []
    images = []
    materials = []
    primitives = []
    used = {}

    def accessor(data, kind, component, extents=False):
        buf = np.ascontiguousarray(data)
        views.append({"buffer": 0, "byteOffset": len(payload), "byteLength": buf.nbytes})
        payload.extend(aligned(buf.tobytes(), b"\0"))
        a = {
            "bufferView": len(views) - 1,
            "componentType": component,
            "count": len(buf),
            "type": kind,
        }
        if extents:
            a.update(min=buf.min(axis=0).tolist(), max=buf.max(axis=0).tolist())
        accessors.append(a)
        return len(accessors) - 1

    bounds = []
    count = 0
    for vv, uv, idx, material_ids, colors in parts:
        if not len(idx):
            continue
        pos = accessor(vv.astype("<f4"), "VEC3", 5126, True)
        uv_id = accessor(uv.astype("<f4"), "VEC2", 5126)
        bounds.extend((vv.min(axis=0), vv.max(axis=0)))
        for matid in np.unique(material_ids):
            tex = colors[matid]
            key, alpha = texture(tex)
            if key not in used:
                used[key] = len(materials)
                images.append({"uri": "/detail/texture/" + key + ".png"})
                mat = {
                    "pbrMetallicRoughness": {
                        "baseColorTexture": {"index": len(images) - 1},
                        "metallicFactor": 0,
                        "roughnessFactor": 1,
                    },
                    "doubleSided": True,
                }
                if alpha:
                    mat.update(alphaMode="MASK", alphaCutoff=0.49)
                materials.append(mat)
            faces = idx[material_ids == matid].reshape(-1)
            component = 5123 if len(vv) <= 65535 else 5125
            index = accessor(
                faces.astype("<u2" if component == 5123 else "<u4"), "SCALAR", component
            )
            primitives.append(
                {
                    "attributes": {"POSITION": pos, "TEXCOORD_0": uv_id},
                    "indices": index,
                    "material": used[key],
                }
            )
            count += len(faces) // 3
    if not primitives:
        return None
    desc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": primitives}],
        "buffers": [{"byteLength": len(payload)}],
        "bufferViews": views,
        "accessors": accessors,
        "materials": materials,
        "images": images,
        "textures": [{"source": i} for i in range(len(images))],
    }
    desc = aligned(json.dumps(desc, separators=(",", ":")).encode(), b" ")
    glb = (
        struct.pack("<4sIIII", b"glTF", 2, 28 + len(desc) + len(payload), len(desc), 0x4E4F534A)
        + desc
        + struct.pack("<II", len(payload), 0x004E4942)
        + payload
    )
    return (
        gzip.compress(glb, compresslevel=3, mtime=0),
        np.min(bounds, axis=0),
        np.max(bounds, axis=0),
        count,
    )


def build(source, adapter, output, *, texture_size=256):
    g = load_local_adapter(source, adapter)
    placements = defaultdict(list)
    for p in g.active_exterior():
        placements[p.name].append(p)
    meta = inventory(source, "black-russia-ariane")
    src = source / "models/img"
    models = g.index_files(sorted(src.glob("br_models_*.img")) + [src / "br_terrain_models.img"])
    types = model_types(source)
    packs = g.definition_dicts(source)
    detailed = texture_size > 256
    textures = Textures(source, g, texture_size=texture_size, pack_cache=12 if detailed else 48)
    output.mkdir(parents=True, exist_ok=True)
    tmp = output / "detail-scene.tmp.sqlite"
    if tmp.exists():
        raise FileExistsError(tmp)
    db = sqlite3.connect(tmp)
    try:
        db.executescript("""
        create table model(id integer primary key,name text unique,triangles integer,glb blob);
        create table texture(key text primary key,png blob) without rowid;
        create table instance(id integer primary key,model integer,x real,y real,z real,qx real,qy real,qz real,qw real);
        create virtual table spatial using rtree(id,minx,maxx,miny,maxy,minz,maxz);
        create table meta(value text);""")
        known = {}

        def save_tex(image):
            rgba = np.ascontiguousarray(image, dtype="u1")
            key = hashlib.sha256(struct.pack("<II", *rgba.shape[:2]) + rgba.tobytes()).hexdigest()
            if key not in known:
                buf = io.BytesIO()
                Image.fromarray(rgba).save(buf, format="PNG", compress_level=3)
                db.execute("insert into texture values (?,?)", (key, buf.getvalue()))
                known[key] = bool(np.min(rgba[:, :, 3]) < 125)
            return key, known[key]

        inst_count = 0
        unique = 0
        placed_count = 0
        empty = []
        for name, location in sorted(models.items(), key=lambda kv: kv[1][:2]):
            bare = name.removesuffix(".dff")
            if bare not in placements:
                continue
            blob = g.read_entry(models, name)
            splat = (
                terrain_materials(blob, include_tiling=detailed) if b"\x20\x01\0\0" in blob else []
            )

            def parts():
                for v, mesh in instance_parts(blob, types[bare]):
                    faces = np.asarray(
                        [(f.a, f.b, f.c, f.material) for f in mesh.triangles], dtype="i4"
                    ).reshape(-1, 4)
                    faces = faces[(faces[:, 3] >= 0) & (faces[:, 3] < len(mesh.materials))]
                    if not len(faces):
                        continue
                    ids = np.unique(faces[:, 3])
                    colors = {
                        i: textures.material(
                            packs.get(bare, ""),
                            mesh.materials[i],
                            splat[i] if i < len(splat) else (),
                        )
                        for i in ids
                    }
                    uv = (
                        np.asarray(mesh.uv_layers[0])
                        if mesh.uv_layers and len(mesh.uv_layers[0]) == len(v)
                        else np.zeros((len(v), 2))
                    )
                    yield v, uv, faces[:, :3], faces[:, 3], colors

            mesh = mesh_file(parts(), save_tex)
            if not mesh:
                empty.append(bare)
                continue
            glb, lo, hi, tris = mesh
            idx = db.execute(
                "insert into model(name,triangles,glb) values (?,?,?)", (bare, tris, glb)
            ).lastrowid
            corners = list(itertools.product(*zip(lo, hi, strict=True)))
            for p in placements[bare]:
                rot = g.ariane_rotation(p.quat)
                world = rot.apply(corners) + p.position
                key = db.execute(
                    "insert into instance(model,x,y,z,qx,qy,qz,qw) values(?,?,?,?,?,?,?,?)",
                    (idx, *p.position, *rot.as_quat()),
                ).lastrowid
                a, b = world.min(axis=0), world.max(axis=0)
                db.execute(
                    "insert into spatial values(?,?,?,?,?,?,?)",
                    (key, a[0], b[0], a[1], b[1], a[2], b[2]),
                )
            inst_count += len(placements[bare])
            unique += tris
            placed_count += tris * len(placements[bare])
            if idx % 500 == 0:
                db.commit()
                print(idx, inst_count, placed_count, flush=True)
        report = {
            "revision": meta["placement_revision"],
            "sourcePlacements": meta["exterior_placements"],
            "visiblePlacements": inst_count,
            "uniqueTriangles": unique,
            "placedTriangles": placed_count,
            "models": db.execute("select count(*) from model").fetchone()[0],
            "textures": len(known),
            "emptyModels": empty,
            "missingTextures": dict(textures.stats),
            "textureLimit": texture_size,
        }
        db.execute("insert into meta values (?)", (json.dumps(report),))
        db.commit()
    finally:
        db.close()
    tmp.replace(output / "detail-scene.sqlite")
    (output / "detail-scene.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "adapter", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--texture-size", type=int, choices=(256, 512, 1024), default=256)
    args = p.parse_args()
    build(args.source, args.adapter, args.output, texture_size=args.texture_size)
