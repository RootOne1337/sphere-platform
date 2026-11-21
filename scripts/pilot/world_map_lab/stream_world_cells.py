"""Stage a full world as spatial IPL cells with cell-local LOD references for the WASM port."""

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
from collections import defaultdict
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.browser_world_scenes import lod_groups, placements
from scripts.pilot.world_map_lab.native_collisions import ENTRY, SECTOR, img_directory

ROW = struct.Struct("<7f3i")
MAGIC = b"BRC1"
CELL_SIDE = 512


def collect(folder, files):
    cells = defaultdict(list)
    for file in files:
        rows = placements(folder / file)
        links = [parent for _, parent in rows]
        for group in lod_groups(links):
            origin = rows[group[0]][0].split(",")
            cell = cells[tuple(math.floor(float(v) / CELL_SIDE) for v in origin[3:5])]
            index = {old: len(cell) + i for i, old in enumerate(group)}
            for old in group:
                payload, parent = rows[old]
                fields = payload.split(",")
                posrot = [float(x) for x in fields[3:10]]
                if not all(map(math.isfinite, posrot)):
                    raise ValueError("non-finite placement")
                cell.append(
                    ROW.pack(
                        *posrot,
                        int(fields[0]),
                        int(fields[2]),
                        index[parent] if parent >= 0 else -1,
                    )
                )
    return cells


def stage(game, dest, overlay=None, mission=None, texture_profile="source", neutral_colour=False):
    if texture_profile not in ("source", "bc", "mip256"):
        raise ValueError("unknown texture profile")
    game = game.resolve(strict=True)
    dest = dest.resolve()
    if dest.exists() or dest.is_relative_to(game):
        raise ValueError("fresh separate output required")
    layout = Path("data/maps/brworld")
    gta_path = Path("data/gta.dat")
    lines = (game / gta_path).read_text("ascii").splitlines()
    files = [
        Path(line.split(maxsplit=1)[1].replace("\\", "/"))
        for line in lines
        if line.strip().lower().startswith("ipl ")
    ]
    if not files or len(set(files)) != len(files) or any(p.parent != layout for p in files):
        raise ValueError("unexpected IPL layout")
    cells = collect(game, files)
    if len(cells) >= 255 or max(map(len, cells.values())) > 4096:
        raise ValueError("cell or entity table too large")
    with TemporaryDirectory(dir=dest.parent) as tmp:
        out = Path(tmp) / "game"

        def link(src, dst):
            src = Path(src)
            if (
                texture_profile != "source"
                and src.suffix.lower() == ".img"
                and (src.parent == game / layout or (overlay and src.parent == overlay))
            ):
                from scripts.pilot.world_map_lab.browser_block_textures import block_native
                from scripts.pilot.world_map_lab.browser_mip_levels import (
                    transform_archive,
                    transform_dictionary,
                    write_mip_archive,
                )

                if texture_profile == "bc":
                    transform_archive(
                        src, Path(dst), lambda raw: transform_dictionary(raw, block_native)
                    )
                else:
                    write_mip_archive(src, Path(dst), 256)
                return

            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        shutil.copytree(
            game,
            out,
            copy_function=link,
            ignore=lambda p, n: ["gta.dat"] if Path(p) == game / "data" else [],
        )
        bank = out / layout / "brcells.img"
        report = []
        with bank.open("xb") as stream:
            table = []
            stream.seek(math.ceil((8 + ENTRY.size * len(cells)) / SECTOR) * SECTOR)
            for i, (key, rows) in enumerate(sorted(cells.items())):
                name = f"brcell{i:03d}.ipl"
                data = MAGIC + struct.pack("<I", len(rows)) + b"".join(rows)
                table.append(
                    ENTRY.pack(
                        stream.tell() // SECTOR, math.ceil(len(data) / SECTOR), 0, name.encode()
                    )
                )
                stream.write(data)
                stream.write(bytes(-len(data) % SECTOR))
                report.append(
                    dict(
                        name=name,
                        cell=key,
                        instances=len(rows),
                        lodLinks=sum(ROW.unpack(x)[-1] >= 0 for x in rows),
                        sha256=hashlib.sha256(data).hexdigest(),
                    )
                )
            stream.seek(0)
            stream.write(struct.pack("<4sI", b"VER2", len(table)))
            stream.writelines(table)
        directory = img_directory(bank)
        with bank.open("rb") as f:
            for item in report:
                _, off, _ = directory[item["name"]]
                f.seek(off)
                if (
                    hashlib.sha256(f.read(8 + ROW.size * item["instances"])).hexdigest()
                    != item["sha256"]
                ):
                    raise ValueError("streamed placement verification failed")
        # A text scene triggers the engine's ordinary first-IPL resource initialization.
        (out / layout / "branchor.ipl").write_bytes(b"inst\nend\n")
        first = next(i for i, line in enumerate(lines) if line.strip().lower().startswith("ipl "))
        lines = (
            lines[:first]
            + [r"IMG data\maps\brworld\brcells.img", r"IPL data\maps\brworld\branchor.ipl"]
            + [line for line in lines[first:] if not line.strip().lower().startswith("ipl ")]
        )
        visual = None
        if overlay:
            visual = json.loads((overlay / "report.json").read_bytes())
            banks = visual["banks"]
            if (
                not banks
                or len(set(banks)) != len(banks)
                or any(name != f"brvis{i:02d}.img" for i, name in enumerate(banks))
            ):
                raise ValueError("invalid visual overlay bank list")
            from scripts.pilot.world_map_lab.compact_browser_textures import read_bindings

            ide = out / layout / "brworld.ide"
            source_sha = hashlib.sha256(ide.read_bytes()).hexdigest()
            if visual.get("sourceIdeSha256", source_sha) != source_sha:
                raise ValueError("overlay built from different model definitions")
            original_rows = ide.read_text("ascii").splitlines()
            original_models, _ = read_bindings(original_rows)
            patched = overlay / "brworld.ide"
            patched_rows = patched.read_text("ascii").splitlines()
            patched_models, _ = read_bindings(patched_rows)

            def ids(rows):
                return {
                    int(f[0]): f[1].strip().lower()
                    for line in rows
                    if len(f := line.split(",")) >= 5 and f[0].strip().isdigit()
                }

            if ids(original_rows) != ids(patched_rows):
                raise ValueError("overlay changes placement model IDs")
            if original_models.keys() != patched_models.keys():
                raise ValueError("overlay model set differs from the world")
            ide.unlink()
            link(patched, ide)
            visual["ideSha256"] = hashlib.sha256(ide.read_bytes()).hexdigest()
            first_bank = next(
                i
                for i, line in enumerate(lines)
                if line.lower().replace(chr(92), "/").startswith("img data/maps/brworld/")
            )
            for name in banks:
                link(overlay / name, out / layout / name)
            lines[first_bank:first_bank] = [
                f"IMG data/maps/brworld/{name}".replace("/", chr(92)) for name in banks
            ]
        (out / gta_path).write_text("\n".join(lines) + "\n", encoding="ascii")
        (out / "sphere-world-cells.json").write_text(json.dumps(report, indent=2), encoding="utf8")
        manifest_path = out / "sphere-full-world.json"
        m = json.loads(manifest_path.read_bytes())
        manifest_path.unlink()
        if visual:
            m["additionalImageArchives"] += len(visual["banks"])
            m["browserDataMod"]["ideSha256"] = visual["ideSha256"]
            m["materialOverlay"] = visual
        if mission:
            scenario = json.loads((mission / "classic-scenario.json").read_bytes())
            if scenario["routeSha256"] != m["routeSha256"] or set(scenario["files"]) != {
                "main.scm",
                "script.img",
            }:
                raise ValueError("scenario does not match the world route")
            for name, digest in scenario["files"].items():
                src = mission / name
                if hashlib.sha256(src.read_bytes()).hexdigest() != digest:
                    raise ValueError("scenario file mismatch")
                target = out / "data/script" / name
                target.unlink()
                link(src, target)
            m["scenarioFiles"] = scenario["files"]
        if neutral_colour:
            from scripts.pilot.world_map_lab.stage_game_quarter import neutral_postfx

            timecycle = out / "data/timecyc.dat"
            timecycle.unlink()
            neutral_postfx(game / "data/timecyc.dat", timecycle)
            m["timecycleSha256"] = hashlib.sha256(timecycle.read_bytes()).hexdigest()
        m["textureProfile"] = texture_profile
        m["additionalImageArchives"] += 1
        m["layoutSha256"]["gta.dat"] = hashlib.sha256((out / gta_path).read_bytes()).hexdigest()
        m["streamedWorld"] = dict(
            cells=len(report),
            instances=sum(c["instances"] for c in report),
            lodLinks=sum(c["lodLinks"] for c in report),
            indexSha256=hashlib.sha256((out / "sphere-world-cells.json").read_bytes()).hexdigest(),
        )
        manifest_path.write_text(json.dumps(m, indent=2), encoding="utf8")
        from scripts.pilot.world_map_lab.restore_world_ranges import upgrade_in_staging

        restored = upgrade_in_staging(out)
        if restored:
            m = json.loads(manifest_path.read_bytes())
        out.rename(dest)
    return m["streamedWorld"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("game", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--overlay", type=Path)
    p.add_argument("--mission", type=Path)
    p.add_argument("--texture-profile", choices=["source", "bc", "mip256"], default="source")
    p.add_argument("--neutral-colour", action="store_true")
    a = p.parse_args()
    print(stage(a.game, a.output, a.overlay, a.mission, a.texture_profile, a.neutral_colour))
