"""Resolve native map model IDs against the selected game's retained definitions."""

import re
import struct

from scripts.pilot.world_map_lab.export_full_game_world import (
    check_scene,
    definitions,
    img_directory,
)
from scripts.pilot.world_map_lab.native_collisions import COL


def allocate(models, occupied):
    # A signed 16-bit reference can appear in older engine structures. Keep IDs in that range.
    reserved = occupied | set(models.values())
    free = (slot for slot in range(1000, 32768) if slot not in reserved)
    result = dict(models)
    for name, old in sorted(models.items(), key=lambda pair: pair[1]):
        if old in occupied:
            value = next(free, None)
            if value is None:
                raise ValueError("not enough free 16-bit model IDs in selected base")
            result[name] = value
    return result


def bind_text(path, original, assigned):
    lines = path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    changed = 0
    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)(\d+)(\s*,\s*)([^,\s]+)\s*,", line)
        if not match:
            continue
        name = match[4].lower()
        if original.get(name) != int(match[2]):
            raise ValueError(f"unbound {name} in {path.name}")
        if original[name] != assigned[name]:
            lines[i] = line[: match.start(2)] + str(assigned[name]) + line[match.end(2) :]
            changed += 1
    if changed:
        path.write_text("".join(lines), encoding="utf-8")
    return changed


def bind_archive(path, original, assigned, seen):
    """Edit only the two ID bytes in each copied collision header; verify each written bank."""
    changed = 0
    directory = img_directory(path)
    with path.open("r+b") as f:
        for entry, (_, start, size) in directory.items():
            if not entry.endswith(".col"):
                continue
            f.seek(start)
            raw = bytearray(f.read(size))
            offset = 0
            touched = False
            while raw[offset : offset + 4] in (b"COLL", b"COL2", b"COL3"):
                if offset + COL.size > len(raw):
                    raise ValueError("truncated collision header")
                _, length, label, old = COL.unpack_from(raw, offset)
                end = offset + 8 + length
                name = label.partition(b"\0")[0].decode("ascii").lower()
                if (
                    name in seen
                    or original.get(name) != old
                    or not offset + COL.size <= end <= len(raw)
                ):
                    raise ValueError(f"invalid native collision reference: {name}")
                seen.add(name)
                if old != assigned[name]:
                    struct.pack_into("<H", raw, offset + COL.size - 2, assigned[name])
                    changed += 1
                    touched = True
                offset = end
            if not offset or any(raw[offset:]):
                raise ValueError("invalid streamed collision padding")
            if touched:
                f.seek(start)
                f.write(raw)
                f.seek(start)
                if f.read(size) != raw:
                    raise OSError("collision binding failed readback")
    return changed


def bind_world(folder, manifest, occupied):
    ide = folder / "brworld.ide"
    original, _, _ = definitions(ide)
    assigned = allocate(original, occupied)
    models = bind_text(ide, original, assigned)
    if definitions(ide)[0] != assigned:
        raise ValueError("rebound native IDE differs")
    instances = 0
    for scene in manifest["scenes"]:
        path = folder / scene["packaged"]
        instances += bind_text(path, original, assigned)
        measured = check_scene(path, assigned)
        measured["areas"] = {str(k): v for k, v in measured["areas"].items()}
        if any(scene[k] != value for k, value in measured.items()):
            raise ValueError(f"placement geometry changed in {path.name}")
    seen = set()
    collisions = sum(
        bind_archive(folder / archive["name"], original, assigned, seen)
        for archive in manifest["archives"]
    )
    if len(seen) != manifest["collisions"]:
        raise ValueError("collision count differs after native binding")
    return {
        "remappedModels": models,
        "remappedInstances": instances,
        "remappedCollisions": collisions,
        "checkedCollisions": len(seen),
        "highestModelId": max(assigned.values()),
    }
