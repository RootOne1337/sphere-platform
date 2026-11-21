"""Compare original Ariane map assets against the active streamed game without using build counters."""

import argparse
import hashlib
import json
import math
import struct
import tomllib
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
from pathlib import Path

from scripts.pilot.world_map_lab.browser_mip_levels import chunk, chunks
from scripts.pilot.world_map_lab.browser_world_scenes import placements
from scripts.pilot.world_map_lab.check_browser_materials import audit as audit_materials
from scripts.pilot.world_map_lab.compact_browser_textures import dictionary
from scripts.pilot.world_map_lab.export_full_game_world import definitions
from scripts.pilot.world_map_lab.native_collisions import COL, img_directory
from scripts.pilot.world_map_lab.stage_game_quarter import directives

TRANSFORM = struct.Struct("<7f")
INSTANCE = struct.Struct("<7fiii")


def placed(name, area, values):
    if not all(map(math.isfinite, values)):
        raise ValueError("non-finite placement")
    return name, area, TRANSFORM.pack(*values)


def count_parented(rows):
    """Include the actual target identity, independent of how the exporter renumbered a cell."""
    result = Counter()
    for key, parent in rows:
        if not -1 <= parent < len(rows):
            raise ValueError("out-of-range LOD target")
        result[(key, None if parent == -1 else rows[parent][0])] += 1
    return result


def source_rows(root, scene, model_ids):
    path = root / scene
    rows = []
    for raw, parent in placements(path):
        ident, model, area, *pose = (v.strip().lower() for v in raw.split(","))
        if model_ids.get(model) != int(ident):
            raise ValueError(f"unbound source model {model}")
        rows.append((placed(model, int(area), tuple(map(float, pose))), parent))
    unavailable = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if line.strip().lower().startswith("# unavailable source:"):
            parts = line.split(":", 1)[1].strip().split(",")
            unavailable.append(
                dict(
                    scene=scene,
                    model=parts[1].strip(),
                    area=int(parts[2]),
                    xyz=[float(s) for s in parts[3:6]],
                )
            )
    return count_parented(rows), unavailable


def cell_rows(raw, names, near_ids=None):
    if len(raw) < 8 or raw[:4] not in (b"BRC1", b"BRC2"):
        raise ValueError("invalid cell header")
    extended = raw[:4] == b"BRC2"
    count = struct.unpack_from("<I", raw, 4)[0]
    stride = INSTANCE.size + 4 * extended
    end = 8 + count * stride
    if end > len(raw) or any(raw[end:]):
        raise ValueError("invalid cell length or padding")
    rows = []
    for off in range(8, end, stride):
        *pose, ident, area, parent = INSTANCE.unpack_from(raw, off)
        if extended and near_ids is not None:
            mark = struct.unpack_from("<I", raw, off + INSTANCE.size)[0]
            if mark != int(ident in near_ids):
                raise ValueError(f"incorrect near-collider role for {names[ident]}")
        rows.append((placed(names[ident], area, pose), parent))
    return count_parented(rows)


def draw_ranges(path):
    result = {}
    section = None
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        row = raw.partition("#")[0].strip().lower()
        if row == "end":
            section = None
        elif row and section is None:
            section = row
        elif row and section in ("objs", "tobj", "anim"):
            parts = row.split(",")
            result[parts[1].strip()] = float(parts[4 if section == "anim" else 3])
    return result


def model_signature(raw):
    """Hash frames, instances, geometry, vertex attributes and splits independently of material bake and bounds."""

    def canonical(blob, parent):
        for tag, rev, data in chunks(blob):
            if tag in (16, 26, 15):
                data = b"".join(canonical(data, tag))
            elif parent == 15 and tag == 8:
                continue
            elif parent == 15 and tag == 1:
                flags, nt, nv, targets = struct.unpack_from("<4I", data)
                if not flags & 0x01000000:
                    uv = (flags >> 16) & 255 or (2 if flags & 128 else int(bool(flags & 4)))
                    pos = 16 + nv * (4 * int(bool(flags & 8)) + 8 * uv) + 8 * nt
                    data = bytearray(data)
                    for _ in range(targets):
                        vertices, normals = struct.unpack_from("<II", data, pos + 16)
                        data[pos : pos + 16] = bytes(16)
                        pos += 24 + 12 * nv * (bool(vertices) + bool(normals))
                    if pos != len(data):
                        raise ValueError("inconsistent morph geometry")
            yield chunk(tag, rev, data)

    # An animated DFF can carry a UV dictionary in front of its clump.
    at = 0
    digest = hashlib.sha256()
    while at + 12 <= len(raw):
        kind, size, _rev = struct.unpack_from("<III", raw, at)
        end = at + 12 + size
        if end > len(raw) or kind not in (0x2B, 0x10):
            raise ValueError("invalid clump")
        for block in canonical(raw[at:end], None):
            digest.update(block)
        at = end
        if kind == 0x10:
            if any(raw[at:]):
                raise ValueError("unexpected data after clump")
            return digest.digest()
    raise ValueError("missing clump")


def archives(root, entries, last_wins):
    index = {}
    for kind, relative in entries:
        if kind == "IMG":
            for key, record in img_directory(root / relative).items():
                if last_wins or key not in index:
                    index[key] = record
    return index


def records(index, handles, name):
    path, offset, size = index[name]
    handle = handles[path]
    handle.seek(offset)
    data = handle.read(size)
    if len(data) != size:
        raise EOFError(name)
    return data


def collisions(data):
    at = 0
    while data[at : at + 4] in (b"COLL", b"COL2", b"COL3"):
        _tag, size, name, ident = COL.unpack_from(data, at)
        end = at + 8 + size
        if not at + COL.size <= end <= len(data):
            raise ValueError("invalid COL record")
        # The packed model ID is translated. All shape and surface data must match.
        yield (
            name.partition(b"\0")[0].decode("ascii").lower(),
            ident,
            hashlib.sha256(data[at : at + COL.size - 2] + data[at + COL.size : end]).digest(),
        )
        at = end
    if not at or any(data[at:]):
        raise ValueError("unknown collision payload")


def texture_layout(index, handles, name):
    path, offset, length = index[name]
    stream = handles[path]
    _, members = dictionary(stream, offset, length)
    rasters = {}
    for texture, start, _ in members:
        stream.seek(start + 24 + 80)
        width, height, _, levels = struct.unpack("<HHBB", stream.read(6))
        key = texture.decode("ascii")
        if key in rasters:
            raise ValueError(f"ambiguous raster {name}/{key}")
        rasters[key] = (width, height, levels)
    return rasters


def compare_textures(game, source_index, game_index, handles):
    binding = json.loads((game / "sphere-texture-packing.json").read_bytes())["binding"]

    @lru_cache(maxsize=48)
    def native(pack):
        return texture_layout(game_index, handles, pack)

    missing = []
    count = 0
    for key in sorted(n for n in source_index if n.endswith(".txd")):
        dest = binding.get(key[:-4], key[:-4]) + ".txd"
        actual = native(dest) if dest in game_index else {}
        for name, layout in texture_layout(source_index, handles, key).items():
            count += 1
            if actual.get(name) != layout:
                missing.append(
                    dict(
                        source=key,
                        packed=dest,
                        texture=name,
                        expected=layout,
                        actual=actual.get(name),
                    )
                )
    return count, missing


def differences(counter):
    def row(key):
        return [key[0], key[1], *TRANSFORM.unpack(key[2])]

    return [
        dict(count=n, instance=row(k), lod=row(p) if p else None) for (k, p), n in counter.items()
    ]


def audit(source, game, mod):
    original = list(directives(source / "data/default.dat"))
    native = list(directives(game / "data/gta.dat"))
    (original_ide,) = (source / path for kind, path in original if kind == "IDE")
    # Browser map definitions are registered by the native mod on startup.
    mod_config = tomllib.loads((mod / "mod.toml").read_text(encoding="utf8"))
    (ide_name,) = mod_config["data"]["ide"]
    active_ide = mod / ide_name
    if active_ide.read_bytes() != (game / "data/maps/brworld/brworld.ide").read_bytes():
        raise ValueError("deployed model definitions differ from staged map")
    ids = definitions(original_ide)[0]
    active_ids = definitions(active_ide)[0]
    native_names = {i: name for name, i in active_ids.items()}
    original_distances = draw_ranges(original_ide)
    actual_distances = draw_ranges(active_ide)
    packing = json.loads((game / "sphere-texture-packing.json").read_bytes())
    near_ids = {active_ids[name] for name in packing["nearCollisionModels"]["changed"]}
    source_index = archives(source, original, last_wins=True)
    game_index = archives(game, native, last_wins=False)
    expected, actual = Counter(), Counter()
    gaps, scenes = [], {}
    for kind, path in directives(source / "data/gta.dat"):
        if kind == "IPL":
            items, skipped = source_rows(source, path, ids)
            scenes[path] = items.total()
            expected.update(items)
            gaps.extend(skipped)
    index = json.loads((game / "sphere-world-cells.json").read_bytes())
    source_dffs = sorted(n for n in source_index if n.endswith(".dff"))
    checks = dict(
        missingDefinitions=sorted(ids.keys() - active_ids.keys()),
        extraDefinitions=sorted(active_ids.keys() - ids.keys()),
        missingModels=[],
        geometryDifferences=[],
        collisionDifferences=[],
        extraCollisions=[],
    )
    checks["drawRangeDifferences"] = [
        name
        for name, distance in original_distances.items()
        if distance != actual_distances.get(name)
    ]
    collision_count = 0
    with ExitStack() as stack:
        files = {
            p: stack.enter_context(p.open("rb"))
            for idx in (source_index, game_index)
            for p in {v[0] for v in idx.values()}
        }
        cell_names = {n for n in game_index if n.startswith("brcell") and n.endswith(".ipl")}
        indexed = [item["name"] for item in index]
        if len(set(indexed)) != len(indexed) or cell_names != set(indexed):
            raise ValueError("cell index differs from active IMG directory")
        for item in index:
            actual.update(
                cell_rows(records(game_index, files, item["name"]), native_names, near_ids)
            )
        for name in source_dffs:
            if name not in game_index:
                checks["missingModels"].append(name)
                continue
            src = records(source_index, files, name)
            dst = records(game_index, files, name)
            if src != dst and model_signature(src) != model_signature(dst):
                checks["geometryDifferences"].append(name)
        raster_count, checks["rasterDifferences"] = compare_textures(
            game, source_index, game_index, files
        )
        for bank in (n for n in source_index if n.endswith(".col")):
            before = {n: h for n, _, h in collisions(records(source_index, files, bank))}
            after = (
                {n: (i, h) for n, i, h in collisions(records(game_index, files, bank))}
                if bank in game_index
                else {}
            )
            collision_count += len(before)
            checks["collisionDifferences"].extend(
                n for n, h in before.items() if after.get(n) != (active_ids.get(n), h)
            )
            checks["extraCollisions"].extend(sorted(after.keys() - before.keys()))
    checks.update(
        missingInstances=differences(expected - actual),
        extraInstances=differences(actual - expected),
    )
    materials = audit_materials(game, active_ide, archive=game_index)
    baseline = audit_materials(source, original_ide, archive=source_index)
    new_missing = []
    for model, item in materials["unresolved"].items():
        original_missing = baseline["unresolved"].get(model, {}).get("textures", {})
        for texture, count in item.get("textures", {}).items():
            if count > original_missing.get(texture, 0):
                new_missing.append(
                    dict(
                        model=model, texture=texture, added=count - original_missing.get(texture, 0)
                    )
                )
    checks["newUnresolvedBindings"] = new_missing
    return dict(
        transferPassed=not any(checks.values()),
        transferDifferences=checks,
        scenes=scenes,
        streamedCells=len(index),
        sourcePlacements=expected.total(),
        runtimePlacements=actual.total(),
        sourceLodLinks=sum(n for (_, parent), n in expected.items() if parent),
        modelFiles=len(source_dffs),
        sourceColliders=collision_count,
        sourceRasterEntries=raster_count,
        unavailableSourceRows=gaps,
        sourceMaterialCounts=baseline["counts"],
        materials=materials,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("source", "game", "mod", "report"):
        parser.add_argument(arg, type=Path)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="also fail on unavailable source placements or unresolved rendered materials",
    )
    args = parser.parse_args()
    result = audit(args.source, args.game, args.mod)
    with args.report.open("x", encoding="utf8") as out:
        json.dump(result, out, ensure_ascii=False, indent=2)
    print(
        "placements",
        result["runtimePlacements"],
        "models",
        result["modelFiles"],
        "colliders",
        result["sourceColliders"],
        "transfer",
        result["transferPassed"],
        "missing from source",
        len(result["unavailableSourceRows"]),
        result["materials"]["counts"],
    )
    raise SystemExit(
        int(
            not result["transferPassed"]
            or (
                args.require_complete
                and (
                    bool(result["unavailableSourceRows"])
                    or result["materials"]["counts"].get("modelsWithUnresolvedDraws", 0) > 0
                )
            )
        )
    )
