"""Inventory the authored map and the separate inputs for a GTA SA gameplay runtime."""

import argparse
import json
import struct
from collections import Counter
from pathlib import Path

# The IMG may contain vehicle-specific animation groups. The main pedestrian
# package and simulation configuration are opened as loose files by the game.
GAME_FILES = {
    "models/gta3.img": "основной архив",
    "anim/ped.ifp": "основная анимация персонажа",
    "data/default.dat": "основные определения",
    "data/gta.dat": "список ресурсов мира",
    "data/surfinfo.dat": "свойства поверхностей",
    "data/surfaud.dat": "звуки контактов с поверхностями",
    "data/handling.cfg": "параметры транспорта",
    "data/vehicles.ide": "определения транспорта",
    "data/peds.ide": "определения персонажей",
    "data/pedstats.dat": "параметры персонажей",
    "data/surface.dat": "материалы для физики",
    "data/script/main.scm": "игровой сценарий",
}


def inspect_source(root):
    entries = set()
    kinds = Counter()
    archives = sorted((root / "models").rglob("*.img"))
    for path in archives:
        with path.open("rb") as stream:
            header = stream.read(8)
            if len(header) != 8 or header[:4] != b"VER2":
                raise ValueError(f"unsupported archive {path.name}")
            count = struct.unpack_from("<I", header, 4)[0]
            if 8 + count * 32 > path.stat().st_size:
                raise ValueError(f"truncated directory in {path.name}")
            for sector, logical, physical, raw in struct.iter_unpack(
                "<IHH24s", stream.read(count * 32)
            ):
                if (sector + (physical or logical)) * 2048 > path.stat().st_size:
                    raise ValueError(f"entry outside {path.name}")
                name = raw.partition(b"\0")[0].decode("ascii").lower()
                entries.add(name)
                kinds[name.rpartition(".")[2]] += 1
    return dict(
        archives=len(archives),
        types=dict(kinds),
        assets={
            k: k in entries
            for k in (
                "player.dff",
                "male01.dff",
                "faggio.dff",
                "faggio.txd",
                "bikev.ifp",
                "ped.ifp",
                "nodes0.dat",
            )
        },
    )


def inspect_runtime(root):
    # These are necessary inputs to the stock gameplay package. Actual readiness
    # is acquired only after the game boots, a ped boards and drives, and exits.
    return {
        path: bool(root and (root / path).is_file() and (root / path).stat().st_size > 0)
        for path in GAME_FILES
    }


def audit(source, game, output):
    report = dict(
        map=inspect_source(source),
        mapFiles=inspect_runtime(source),
        runtimeFiles=inspect_runtime(game),
        gameDirectory=str(game) if game else None,
    )
    report["missingGameFiles"] = [k for k, v in report["runtimeFiles"].items() if not v]
    report["engineDriveVerified"] = False
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
    return report


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--source", required=True, type=Path)
    cli.add_argument("--game", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    result = audit(args.source, args.game, args.output)
    print(json.dumps(result, ensure_ascii=False))
