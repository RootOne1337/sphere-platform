"""Select a local classic PC game, stage the map in its own directory, and launch the game."""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot.world_map_lab.classic_world_limits import CONFIG_NAME
from scripts.pilot.world_map_lab.stage_full_game_world import stage as stage_world
from scripts.pilot.world_map_lab.stage_game_quarter import stage


def digest(file):
    with file.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(game, quarter, scenario, output):
    game = game.resolve(strict=True)
    selected = json.loads((scenario / "classic-scenario.json").read_bytes())
    source_game = game / "gta_sa.exe"
    if not source_game.is_file():
        raise ValueError("Выберите папку классической GTA San Andreas для Windows с gta_sa.exe")
    if not output.exists():
        stage(game, quarter, output, scenario)
    actual = json.loads((output / "sphere-scenario.json").read_bytes())
    if (
        not actual.get("gameplayBasePresent")
        or not actual.get("classicScenario")
        or actual["routeSha256"] != selected["routeSha256"]
        or digest(output / "sphere-route.json") != selected["routeSha256"]
        or digest(source_game) != digest(output / "gta_sa.exe")
        or actual.get("sourceGameDirectory") != str(game)
        or actual.get("mapManifestSha256") != digest(quarter / "manifest.json")
        or any(
            digest(output / "data/script" / name) != selected["files"][name]
            for name in ("main.scm", "script.img")
        )
    ):
        raise ValueError(
            "Подготовленная копия принадлежит другой сборке. Выберите новый каталог для стенда."
        )
    return output / "gta_sa.exe"


def prepare_full(game, world, scenario, output):
    game, world, scenario = (path.resolve(strict=True) for path in (game, world, scenario))
    if not output.exists():
        stage_world(game, world, output, scenario)
    record = json.loads((output / "sphere-full-world.json").read_bytes())
    selected = json.loads((scenario / "classic-scenario.json").read_bytes())
    valid = (
        record["sourceGameDirectory"] == str(game)
        and record["worldManifestSha256"] == digest(world / "world-manifest.json")
        and record["routeSha256"] == selected["routeSha256"] == digest(output / "sphere-route.json")
        and record["gameExecutableSha256"]
        == digest(game / "gta_sa.exe")
        == digest(output / "gta_sa.exe")
        and record["limitsSha256"] == digest(output / CONFIG_NAME)
        and all(
            record["layoutSha256"][n] == digest(output / "data" / n)
            for n in ("default.dat", "gta.dat")
        )
        and all(
            record["scenarioFiles"][n] == selected["files"][n] == digest(output / "data/script" / n)
            for n in ("main.scm", "script.img")
        )
    )
    if not valid:
        raise ValueError(
            "Состав подготовленного стенда отличается от выбранной карты, сценария или игры."
        )
    return output / "gta_sa.exe"


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--game", type=Path)
    group = cli.add_mutually_exclusive_group(required=True)
    group.add_argument("--world", type=Path, help="full native Black Russia map")
    group.add_argument("--quarter", type=Path, help="small game fixture")
    for key in ("scenario", "output"):
        cli.add_argument("--" + key, required=True, type=Path)
    cli.add_argument("--prepare-only", action="store_true")
    cli.add_argument(
        "--visual-pilot",
        type=Path,
        nargs=4,
        metavar=("LAB", "SOURCE", "CONTROLLER", "BANK"),
        help="start the mixed RGB pilot and record game video in a new attempt directory",
    )
    cli.add_argument("--hfov", type=float, help="use a measured native camera field of view")
    args = cli.parse_args()
    if args.visual_pilot and (not args.world or args.prepare_only):
        cli.error("--visual-pilot requires launching the full world")
    if args.visual_pilot:
        transfer_bank = (args.scenario / "transfer-views.npz").resolve(strict=True)
        lab, source, controller, bank = (p.resolve(strict=True) for p in args.visual_pilot)
    if args.game is None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        folder = filedialog.askdirectory(title="Классическая GTA San Andreas для Windows")
        root.destroy()
        if not folder:
            raise SystemExit(0)
        args.game = Path(folder)
    if args.world:
        if (
            not args.prepare_only
            and not (args.game / "$fastman92limitAdjuster.asi").is_file()
            and not (args.output / "$fastman92limitAdjuster.asi").is_file()
        ):
            raise SystemExit(
                "Для полной карты требуется fastman92 limit adjuster для классической GTA SA."
            )
        exe = prepare_full(args.game, args.world, args.scenario, args.output.resolve())
        if not args.prepare_only and not (exe.parent / "$fastman92limitAdjuster.asi").is_file():
            raise SystemExit("В подготовленной копии отсутствует расширитель лимитов.")
    else:
        exe = prepare(args.game, args.quarter, args.scenario, args.output.resolve())
    if args.prepare_only:
        print(exe)
    else:
        subprocess.Popen([str(exe)], cwd=exe.parent)
        if args.visual_pilot:
            attempt = (
                exe.parent.parent
                / "native-runs"
                / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            )
            attempt.mkdir(parents=True, exist_ok=False)
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.pilot.world_map_lab.classic_camera_pilot",
                    "--classic",
                    str(exe.parent),
                    "--route",
                    str(exe.parent / "sphere-route.json"),
                    "--lab",
                    str(lab),
                    "--source",
                    str(source),
                    "--controller",
                    str(controller),
                    "--bank",
                    str(bank),
                    "--transfer-bank",
                    str(transfer_bank),
                    "--actuate",
                    "--output",
                    str(attempt / "decisions.jsonl"),
                    "--movie",
                    str(attempt / "first-person.mp4"),
                    *(["--hfov", str(args.hfov)] if args.hfov is not None else []),
                ],
                check=True,
            )
