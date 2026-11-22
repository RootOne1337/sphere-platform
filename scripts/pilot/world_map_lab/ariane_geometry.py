"""RenderWare geometry with Ariane's placement-frame rules."""

from __future__ import annotations

from collections import Counter
from importlib import import_module

import numpy as np

REGIONS = {
    "batyrevo": (1374.0, 2957.0, 1505.0, 3000.0),
    "arzamas_north": (-1034.0, 984.0, 1068.0, 2091.0),
    "nizhny": (-3035.0, -1680.0, 2140.0, 3139.0),
    "uzhny": (1550.0, 3060.0, -2960.0, -1510.0),
}


def model_types(source):
    types = {}
    for manifest in ("default.dat", "gta.dat"):
        for line in (source / "data" / manifest).read_text(encoding="utf-8-sig").splitlines():
            asset, _, relative = line.strip().partition(" ")
            if asset.upper() != "IDE":
                continue
            ide = source / relative.strip().replace("\\", "/")
            section = ""
            for entry in ide.read_text(encoding="utf-8-sig").splitlines():
                text = entry.split("#", 1)[0].strip()
                if not text:
                    continue
                if text == "end":
                    section = ""
                    continue
                if text in {"objs", "tobj", "anim"}:
                    section = text
                    continue
                if section:
                    fields = text.split(",")
                    if len(fields) >= 3:
                        types[fields[1].strip().lower()] = section
    return types


def scene_parts(model, kind):
    # Ariane's ObjectDef::LoadAtomic detaches atomics and discards their DFF frames.
    # ObjectInst::CreateRwObject replaces the clump root and preserves children.
    if kind in {"objs", "tobj"}:
        original = [
            node.geometry_list[atomic.geometry]
            for node in model.clumps
            for atomic in node.atomic_list
            if not (
                0 <= atomic.frame < len(node.frame_list)
                and (node.frame_list[atomic.frame].name or "").endswith("_dam")
            )
        ]
        if original:
            mesh = original[-1]
            yield np.asarray(mesh.vertices, dtype=np.float64), mesh
        return
    if kind != "anim":
        raise ValueError(f"unknown Ariane model type: {kind}")
    for node in model.clumps:
        for atomic in node.atomic_list:
            mesh = node.geometry_list[atomic.geometry]
            vertices = np.asarray(mesh.vertices, dtype=np.float64)
            index = atomic.frame
            seen = set()
            while 0 < index < len(node.frame_list):
                if index in seen:
                    raise ValueError("cyclic RenderWare frame hierarchy")
                seen.add(index)
                frame = node.frame_list[index]
                vertices = vertices @ np.asarray(frame.rotation_matrix) + np.asarray(frame.position)
                index = frame.parent
            yield vertices, mesh


def instance_parts(blob, kind):
    dff = import_module("gtaLib.dff").dff()
    dff.load_memory(blob)
    for vertices, mesh in scene_parts(dff, kind):
        yield vertices, restore_split_materials(mesh)


def restore_split_materials(mesh):
    """Recover material IDs when the geometry header lost them but Bin Mesh retained them."""
    faces = mesh.triangles
    splits = mesh.extensions.get("mat_split") or ()
    if (
        not faces or len(mesh.materials) < 2 or len(faces) != len(splits)
        or any(face.material != 0 for face in faces)
        or not any(face.material != 0 for face in splits)
    ):
        return mesh

    def key(face):
        return tuple(sorted((face.a, face.b, face.c)))

    materials = {}
    counts = Counter()
    for face in splits:
        ids = key(face)
        if not 0 <= face.material < len(mesh.materials):
            return mesh
        if materials.setdefault(ids, face.material) != face.material:
            return mesh
        counts[ids] += 1
    if counts == Counter(map(key, faces)):
        # Keep the original winding, order and indices for rendering and collision checks.
        mesh.triangles = [face._replace(material=materials[key(face)]) for face in faces]
    return mesh
