"""Use the native sorted draw pass for double-sided foliage and fences with cutout alpha."""

import argparse
import json
import struct
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.browser_world_materials import payload
from scripts.pilot.world_map_lab.check_browser_materials import geometries, material_primitives
from scripts.pilot.world_map_lab.compact_browser_textures import dictionary, read_bindings
from scripts.pilot.world_map_lab.native_collisions import img_directory


def alpha_cutout(alpha):
    """Distinguish a masked surface from opaque art or a translucent glass pane."""
    return (
        np.mean(alpha < 12) >= 0.12
        and np.mean(alpha > 243) >= 0.12
        and np.mean((alpha < 12) | (alpha > 243)) >= 0.70
    )


def sorted_cutouts(game, source):
    lines = source.read_text("ascii").splitlines()
    models, parents = read_bindings(lines)
    directory = {}
    for bank in sorted((game / "data/maps/brworld").glob("brw*.img")):
        directory.update(img_directory(bank))

    @lru_cache(maxsize=None)
    def textures(pack):
        if pack + ".txd" not in directory:
            return {}
        bank, off, size = directory[pack + ".txd"]
        with bank.open("rb") as f:
            _, members = dictionary(f, off, size)
            found = {}
            for key, offset, size in members:
                f.seek(offset + 24)
                header = f.read(92)
                if len(header) != 92:
                    raise ValueError("truncated native texture header")
                w, h = struct.unpack_from("<HH", header, 80)
                cut = False
                if (
                    struct.unpack_from("<I", header, 76)[0] == 21
                    and header[87] & 1
                    and struct.unpack_from("<I", header, 88)[0] == w * h * 4
                ):
                    if w * h * 4 + 116 > size:
                        raise ValueError("source mip exceeds texture")
                    rgba = np.frombuffer(f.read(w * h * 4), np.uint8).reshape(h, w, 4)
                    cut = alpha_cutout(rgba[:: max(1, h // 128), :: max(1, w // 128), 3])
                found[key.decode("ascii")] = cut
        return found

    @lru_cache(maxsize=None)
    def mask(pack, name):
        seen = set()
        while pack and pack not in seen:
            seen.add(pack)
            found = textures(pack)
            if name in found:
                return found[name]
            pack = parents.get(pack)
        return False

    changed = []
    section = None
    for i, row in enumerate(lines):
        body, comment, suffix = row.partition("#")
        stripped = body.strip().lower()
        if not stripped:
            continue
        if section is None:
            section = stripped
            continue
        if stripped == "end":
            section = None
            continue
        if section not in {"objs", "tobj", "anim"}:
            continue
        fields = body.split(",")
        # The two time fields in timed object records follow the flags.
        flag_index = len(fields) - (3 if section == "tobj" else 1)
        name = fields[1].strip().lower()
        if name not in models or flag_index < 4:
            raise ValueError(f"unexpected {section} record {row!r}")
        flags = int(fields[flag_index].strip())
        if not flags & 8192 or flags & 4:
            continue
        if name + ".dff" not in directory:
            continue
        weights = Counter()
        for geom in geometries(payload(directory, name + ".dff")):
            for texture, faces, indices in material_primitives(geom):
                weights[texture] += indices or 3 * faces
        masked = sum(n for texture, n in weights.items() if mask(models[name], texture))
        if masked and masked >= 0.35 * weights.total():
            fields[flag_index] = " " + str(flags | 4)
            lines[i] = ",".join(fields) + comment + suffix
            changed.append(name)
    return lines, changed


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("game", "source", "output", "report"):
        p.add_argument(arg, type=Path)
    opt = p.parse_args()
    lines, models = sorted_cutouts(opt.game, opt.source)
    with opt.output.open("x", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    with opt.report.open("x", encoding="utf8") as f:
        json.dump(models, f, indent=2)
    print("draw order updated for", len(models), "models")
