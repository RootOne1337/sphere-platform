"""Prepare an isolated GTA data tree with the native test quarter and an intact gameplay base."""

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.audit_game_runtime import inspect_runtime

MODEL_LIMIT = 20000


def directives(path):
    for line in path.read_text(encoding="cp1252").splitlines():
        parts = line.split("#", 1)[0].strip().split(maxsplit=1)
        if len(parts) == 2:
            yield parts[0].upper(), parts[1].strip().replace("\\", "/")


def base_ids(game):
    used = set()
    for dat in ("data/default.dat", "data/gta.dat"):
        for kind, path in directives(game / dat):
            if kind != "IDE":
                continue
            asset = (game / path).resolve(strict=True)
            if not asset.is_relative_to(game):
                raise ValueError("IDE outside selected game directory")
            for line in asset.read_text(encoding="cp1252").splitlines():
                if match := re.match(r"^\s*(\d+)\s*,", line):
                    used.add(int(match[1]))
    # Keep engine-reserved characters, vehicles and special slots intact.
    return set(range(1000)) | used


def remap(ide, ipl, used):
    names = {}
    available = iter(i for i in range(1000, MODEL_LIMIT) if i not in used)

    def rewrite(text, definitions):
        output = []
        for line in text.splitlines():
            match = re.match(r"^(\s*)(\d+)(\s*,\s*)([^,]+)(,.*)$", line)
            if match:
                name = match[4].strip().lower()
                if definitions:
                    if name in names:
                        raise ValueError("duplicate model definition " + name)
                    ident = next(available, None)
                    if ident is None:
                        raise ValueError("not enough unused model slots")
                    names[name] = ident
                if name not in names:
                    raise ValueError("unbound placement " + name)
                line = f"{match[1]}{names[name]}{match[3]}{match[4]}{match[5]}"
            output.append(line)
        return "\n".join(output) + "\n"

    return rewrite(ide, True), rewrite(ipl, False), names


def stage(game, quarter, dest):
    game = game.resolve(strict=True)
    quarter = quarter.resolve(strict=True)
    dest = dest.resolve()
    if dest.exists() or dest.is_relative_to(game) or dest.is_relative_to(quarter):
        raise ValueError("select a new directory outside the inputs")
    missing = [p for p, ok in inspect_runtime(game).items() if not ok]
    if missing:
        raise ValueError("missing gameplay inputs: " + ", ".join(missing))
    proof = json.loads((quarter / "manifest.json").read_bytes())
    for name in ("brquarter.col", "brquarter.img", "brquarter.ide", "brquarter.ipl"):
        with (quarter / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != proof["hashes"][name]:
                raise ValueError("native quarter changed: " + name)
    ide, ipl, ids = remap(
        (quarter / "brquarter.ide").read_text("ascii"),
        (quarter / "brquarter.ipl").read_text("ascii"),
        base_ids(game),
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as temp:
        root = Path(temp) / "game"
        root.mkdir()
        # Link only immutable, unmodified assets. Generated config always gets a new file.
        for group in ("anim", "audio", "data", "models", "text", "movies"):
            for src in (game / group).rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(game)
                if rel.as_posix().lower() in ("data/gta.dat", "data/default.dat"):
                    continue
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copyfile(src, dst)
        relative = Path("data/maps/sphere_native")
        patch = root / relative
        patch.mkdir(parents=True, exist_ok=False)
        for name in ("brquarter.col", "brquarter.img"):
            shutil.copyfile(quarter / name, patch / name)
        (patch / "brquarter.ide").write_text(ide, encoding="ascii")
        (patch / "brquarter.ipl").write_text(ipl, encoding="ascii")
        additions = [
            "IMG data/maps/sphere_native/brquarter.img",
            "IDE data/maps/sphere_native/brquarter.ide",
            "COLFILE 0 data/maps/sphere_native/brquarter.col",
            "IPL data/maps/sphere_native/brquarter.ipl",
        ]
        for filename in ("default.dat", "gta.dat"):
            base = (game / "data" / filename).read_text(encoding="cp1252").splitlines()
            remaining = [line for line in base if not re.match(r"^\s*IPL\s+", line, re.I)]
            if filename == "gta.dat":
                exit_at = next(
                    (i for i, line in enumerate(remaining) if line.strip().upper() == "EXIT"),
                    len(remaining),
                )
                remaining[exit_at:exit_at] = additions
            (root / "data" / filename).write_text("\n".join(remaining) + "\n", encoding="cp1252")
        (root / "sphere-scenario.json").write_text(
            json.dumps(
                dict(
                    quarterRevision=proof["revision"],
                    models=ids,
                    start=proof["start"],
                    vehicle=proof["vehicle"],
                    end=proof["end"],
                    vehicleModel=462,
                    engineDriveVerified=False,
                ),
                indent=2,
            ),
            encoding="utf8",
        )
        root.rename(dest)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for key in ("game", "quarter", "output"):
        cli.add_argument("--" + key, required=True, type=Path)
    args = cli.parse_args()
    stage(args.game, args.quarter, args.output)
