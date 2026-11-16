"""RenderWare geometry with Ariane's placement-frame rules."""

from __future__ import annotations

from importlib import import_module

import numpy as np


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
    return scene_parts(dff, kind)
