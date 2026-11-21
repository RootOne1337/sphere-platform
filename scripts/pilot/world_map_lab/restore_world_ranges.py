"""Restore original draw ranges without turning near collision-bearing models into scenery."""

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.export_full_game_world import digest
from scripts.pilot.world_map_lab.native_collisions import ENTRY, SECTOR, img_directory

BASE_ROW = struct.Struct("<7fiii")


def original_ranges(lines, distances):
    ids = set()
    result = []
    section = None
    for raw in lines:
        text, comment, tail = raw.partition("#")
        line = text.strip().lower()
        if line == "end":
            section = None
        elif line and section is None:
            section = line
        elif line and section in ("objs", "tobj", "anim"):
            columns = text.split(",")
            name = columns[1].strip().lower()
            if name in distances:
                index = 4 if section == "anim" else 3
                desired = float(distances[name])
                if not math.isfinite(desired) or desired <= 150 or float(columns[index]) != 150:
                    raise ValueError("unexpected collision profile for " + name)
                ids.add(int(columns[0]))
                columns[index] = " " + format(desired, ".9g")
                raw = ",".join(columns) + comment + tail
        result.append(raw)
    if len(ids) != len(distances):
        raise ValueError("range receipt differs from model definitions")
    return result, ids


def upgrade_in_staging(game):
    manifest = game / "sphere-full-world.json"
    packed = game / "sphere-texture-packing.json"
    if not packed.is_file():
        return
    changes = json.loads(packed.read_bytes())["nearCollisionModels"]["changed"]
    if not changes:
        return
    folder = game / "data/maps/brworld"
    ide = folder / "brworld.ide"
    rows, ids = original_ranges(ide.read_text("ascii").splitlines(), changes)
    bank = folder / "brcells.img"
    index_file = game / "sphere-world-cells.json"
    index = json.loads(index_file.read_bytes())
    table = img_directory(bank)
    header = []
    marked = 0
    with TemporaryDirectory(dir=game) as td:
        tmp = Path(td)
        with bank.open("rb") as src, (tmp / bank.name).open("xb") as dst:
            dst.seek(math.ceil((8 + len(index) * ENTRY.size) / SECTOR) * SECTOR)
            for item in index:
                name = item["name"]
                _, off, length = table[name]
                src.seek(off)
                raw = src.read(length)
                n = item["instances"]
                end = 8 + n * BASE_ROW.size
                if (
                    raw[:4] != b"BRC1"
                    or struct.unpack_from("<I", raw, 4)[0] != n
                    or any(raw[end:])
                    or hashlib.sha256(raw[:end]).hexdigest() != item["sha256"]
                ):
                    raise ValueError("unverified input cell " + name)
                data = bytearray(b"BRC2" + raw[4:8])
                for row in struct.iter_unpack("<40s", raw[8:end]):
                    ident = struct.unpack_from("<i", row[0], 28)[0]
                    near = int(ident in ids)
                    data.extend(row[0])
                    data.extend(struct.pack("<I", near))
                    marked += near
                header.append(
                    ENTRY.pack(
                        dst.tell() // SECTOR, math.ceil(len(data) / SECTOR), 0, name.encode("ascii")
                    )
                )
                dst.write(data)
                dst.write(bytes(-len(data) % SECTOR))
                item["sha256"] = hashlib.sha256(data).hexdigest()
            dst.seek(0)
            dst.write(struct.pack("<4sI", b"VER2", len(header)))
            dst.writelines(header)
        if img_directory(tmp / bank.name).keys() != table.keys():
            raise ValueError("range profile changed cell set")
        (tmp / ide.name).write_text("\n".join(rows) + "\n", encoding="ascii")
        (tmp / index_file.name).write_text(json.dumps(index, indent=2), encoding="utf8")
        m = json.loads(manifest.read_bytes())
        m["browserDataMod"]["ideSha256"] = digest(tmp / ide.name)
        m["streamedWorld"]["indexSha256"] = digest(tmp / index_file.name)
        m["streamedWorld"]["sourceDrawRanges"] = dict(
            models=len(ids), nearInstances=marked, format="BRC2"
        )
        if "materialOverlay" in m:
            m["materialOverlay"]["ideSha256"] = m["browserDataMod"]["ideSha256"]
        (tmp / manifest.name).write_text(json.dumps(m, indent=2), encoding="utf8")
        for f in (bank, ide, index_file, manifest):
            (tmp / f.name).replace(f)
    return m["streamedWorld"]["sourceDrawRanges"]


def upgrade_copy(game, destination):
    game = game.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination.is_relative_to(game):
        raise ValueError("a new staging directory is required")
    with TemporaryDirectory(dir=destination.parent) as td:
        output = Path(td) / "game"

        def copy(src, dst):
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        shutil.copytree(game, output, copy_function=copy)
        result = upgrade_in_staging(output)
        output.rename(destination)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("output", type=Path)
    a = parser.parse_args()
    print(upgrade_copy(a.game, a.output))
