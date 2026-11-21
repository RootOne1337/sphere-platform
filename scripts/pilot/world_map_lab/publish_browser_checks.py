"""Publish the browser engine checks alongside an existing sa-game web build."""

import argparse
import json
import shutil
from pathlib import Path

from scripts.pilot.world_map_lab.audit_game_runtime import GAME_FILES
from scripts.pilot.world_map_lab.export_full_game_world import digest


def sector_sum(data):
    if len(data) != 2048:
        raise ValueError("expected one complete IMG sector")
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


def publish(web, game, manifest, scenario):
    world = json.loads(manifest.read_bytes())
    mission = json.loads((scenario / "classic-scenario.json").read_bytes())
    if mission["worldManifestSha256"] != digest(manifest) or mission["routeSha256"] != digest(
        scenario / "sphere-route.json"
    ):
        raise ValueError("mission and world differ")
    if not (web / "pkg/sa_game_bg.wasm").is_file():
        raise ValueError("build the patched browser engine first")
    banks = []
    paths = ["models/gta3.img", "models/gta_int.img"]
    paths += ["data/maps/brworld/" + a["name"] for a in world["archives"]]
    for path in paths:
        source = game / path
        size = source.stat().st_size
        if size % 2048 or not 2048 <= size <= 2**31:
            raise ValueError(f"unsupported IMG extent: {path}")
        with source.open("rb") as f:
            first = f.read(2048)
            f.seek(-2048, 2)
            last = f.read(2048)
        if first[:4] != b"VER2":
            raise ValueError(f"invalid GTA archive: {path}")
        banks.append(dict(path=path, bytes=size, first=sector_sum(first), last=sector_sum(last)))
    for name in ("main.scm", "script.img"):
        if digest(game / "data/script" / name) != mission["files"][name]:
            raise ValueError("served game has a different mission script")
    spec = dict(
        world=mission["worldManifestSha256"],
        route=mission["routeSha256"],
        scm=mission["files"]["main.scm"],
        scriptImg=mission["files"]["script.img"],
        required=[
            *GAME_FILES,
            "models/player.img",
            "models/gta_int.img",
            "data/maps/brworld/brworld.ide",
            *("data/maps/brworld/" + s["packaged"].lower() for s in world["scenes"]),
            *(a["path"] for a in banks[2:]),
            "data/water.dat",
            "data/timecyc.dat",
        ],
        archiveBytes={a["path"]: a["bytes"] for a in banks[2:]},
    )
    (web / "browser-course.json").write_text(json.dumps(spec), encoding="utf8")
    (web / "archive-check.json").write_text(json.dumps(banks), encoding="utf8")
    for name in ("browser_physics.html", "browser_check_worker.js", "browser_game_folder.js"):
        shutil.copyfile(Path(__file__).with_name(name), web / name)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("web", "game", "manifest", "scenario"):
        cli.add_argument("--" + name, type=Path, required=True)
    args = cli.parse_args()
    publish(args.web, args.game, args.manifest, args.scenario)
