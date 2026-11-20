"""Select a local classic PC game, stage the map in its own directory, and launch the game."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

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


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--game", type=Path)
    for key in ("quarter", "scenario", "output"):
        cli.add_argument("--" + key, required=True, type=Path)
    cli.add_argument("--prepare-only", action="store_true")
    args = cli.parse_args()
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
    exe = prepare(args.game, args.quarter, args.scenario, args.output.resolve())
    if args.prepare_only:
        print(exe)
    else:
        subprocess.Popen([str(exe)], cwd=exe.parent)
