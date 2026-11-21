"""Audit base texture bindings on the actual DFF/TXD files in native IMG load order."""

import argparse
import json
import struct
from collections import Counter, defaultdict
from pathlib import Path

from scripts.pilot.world_map_lab.browser_mip_levels import chunks
from scripts.pilot.world_map_lab.browser_world_materials import payload
from scripts.pilot.world_map_lab.compact_browser_textures import dictionary, read_bindings
from scripts.pilot.world_map_lab.native_collisions import img_directory


def material_names(blob):
    for kind, _, data in chunks(blob):
        if kind in (16, 26, 15, 8, 7):
            yield from material_names(data)
        elif kind == 6:
            name = next(value for tag, _, value in chunks(data) if tag == 2)
            if name.partition(b"\0")[0]:
                yield name.partition(b"\0")[0].decode("ascii").lower()


def geometries(data):
    for tag, v, d in chunks(data):
        if tag in (16, 26):
            yield from geometries(d)
        if tag == 15:
            yield d


def material_primitives(data):
    rows = list(chunks(data))
    header = next(p for k, v, p in rows if k == 1)
    flags, ntri, nv, nm = struct.unpack_from("<4I", header)
    n_uv = (flags >> 16) & 255 or (2 if flags & 128 else int(bool(flags & 4)))
    off = 16 + nv * (4 * int(bool(flags & 8)) + 8 * n_uv)
    faces = Counter(struct.unpack_from("<H", header, off + 8 * i + 4)[0] for i in range(ntri))
    mt = list(chunks(next(p for k, v, p in rows if k == 8)))
    indices = next(p for k, v, p in mt if k == 1)
    count = struct.unpack_from("<I", indices)[0]
    names = iter([list(material_names(p)) for k, v, p in mt if k == 7])
    materials = []
    for (ix,) in struct.iter_unpack("<i", indices[4 : 4 + count * 4]):
        materials.append(next(names) if ix == -1 else materials[ix])
    splits = Counter()
    for tag, _, ext in rows:
        if tag == 3:
            for k, v, p in chunks(ext):
                if k != 0x50E:
                    continue
                fl, n, total = struct.unpack_from("<3I", p)
                pos = 12
                for _ in range(n):
                    sz, mat = struct.unpack_from("<II", p, pos)
                    pos += 8 + sz * 4
                    splits[mat] += sz
                if pos != len(p):
                    raise ValueError("unsupported mesh")
    return [(k, faces[i], splits[i]) for i, names in enumerate(materials) for k in names]


def audit(game, ide, *, archive=None):
    if archive is None:
        archive = {}
        for line in (game / "data/gta.dat").read_text("ascii").splitlines():
            if line.strip().lower().startswith("img "):
                bank = game / line.split(maxsplit=1)[1].replace(chr(92), "/")
                for name, entry in img_directory(bank).items():
                    archive.setdefault(name, entry)
    models, parents = read_bindings(ide.read_text("ascii").splitlines())
    dictionaries = {}
    for name, (f, off, size) in archive.items():
        if name.endswith(".txd"):
            with f.open("rb") as stream:
                _, entries = dictionary(stream, off, size)
            dictionaries[name[:-4]] = {key.decode("ascii") for key, _, _ in entries}
    # A missing package remains visible in the audit; only use actual registered libraries.
    missing = {}
    counts = Counter()
    for model, pack in models.items():
        if model + ".dff" not in archive:
            missing[model] = {"modelFileMissing": True}
            continue
        data = payload(archive, model + ".dff")
        names = Counter(material_names(data))
        counts["modelsChecked"] += 1
        counts["texturedMaterialSlots"] += names.total()
        chain, available = [], set()
        while pack is not None:
            if pack in chain:
                raise ValueError("cyclic texture parent " + repr(chain))
            chain.append(pack)
            available.update(dictionaries.get(pack, ()))
            pack = parents.get(pack)
        unresolved = {k: v for k, v in names.items() if k not in available}
        if unresolved:
            used = defaultdict(lambda: [0, 0])
            for geometry in geometries(data):
                for name, triangles, indices in material_primitives(geometry):
                    if name in unresolved:
                        used[name][0] += triangles
                        used[name][1] += indices
            missing[model] = dict(dictionaries=chain, textures=unresolved, primitives=dict(used))
            counts["modelsWithUnresolvedDraws"] += int(any(n or i for n, i in used.values()))
            counts["unresolvedSlotsOnDraws"] += sum(
                unresolved[name] for name, (n, i) in used.items() if n or i
            )
            counts["unresolvedSlots"] += sum(unresolved.values())
    return dict(counts=counts, unresolvedModels=len(missing), unresolved=missing)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "ide", "report"):
        p.add_argument(name, type=Path)
    args = p.parse_args()
    result = audit(args.game, args.ide)
    with args.report.open("x", encoding="utf8") as dest:
        json.dump(result, dest, indent=2)
    print(result["counts"], "unresolved models", result["unresolvedModels"])
