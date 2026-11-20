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
from scripts.pilot.world_map_lab.native_collisions import bind_collisions, write_game_img

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


def stage(game, quarter, dest, classic=None):
    game = game.resolve(strict=True) if game else None
    quarter = quarter.resolve(strict=True)
    dest = dest.resolve()
    if dest.exists() or (game and dest.is_relative_to(game)) or dest.is_relative_to(quarter):
        raise ValueError("select a new directory outside the inputs")
    missing = [p for p, ok in inspect_runtime(game).items() if not ok]
    if classic and game:
        missing = [p for p in missing if p != "data/script/main.scm"]
        if not (game / "gta_sa.exe").is_file():
            missing.append("gta_sa.exe")
        if not (game / "models/player.img").is_file():
            missing.append("models/player.img")
    if game and missing:
        raise ValueError("missing gameplay inputs: " + ", ".join(missing))
    proof = json.loads((quarter / "manifest.json").read_bytes())
    environment = [name for name in ("water.dat", "timecyc.dat") if name in proof["hashes"]]
    packaged_route = proof.get("routeSha256")
    scripts = {}
    if classic:
        proof_scm = json.loads((classic / "classic-scenario.json").read_bytes())
        if not packaged_route or proof_scm["routeSha256"] != packaged_route:
            raise ValueError("classic scenario belongs to a different route")
        for name in ("main.scm", "script.img"):
            payload = (classic / name).read_bytes()
            if not payload or hashlib.sha256(payload).hexdigest() != proof_scm["files"][name]:
                raise ValueError("classic script changed: " + name)
            scripts[name] = payload
    if packaged_route and packaged_route != proof["hashes"].get("route.json"):
        raise ValueError("route differs from the exported world")
    for name in [
        "brquarter.col",
        "brquarter.img",
        "brquarter.ide",
        "brquarter.ipl",
        *environment,
        *(["route.json"] if packaged_route else []),
    ]:
        with (quarter / name).open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != proof["hashes"][name]:
                raise ValueError("native quarter changed: " + name)
    ide, ipl, ids = remap(
        (quarter / "brquarter.ide").read_text("ascii"),
        (quarter / "brquarter.ipl").read_text("ascii"),
        base_ids(game) if game else set(),
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=dest.parent) as temp:
        root = Path(temp) / "game"
        root.mkdir()
        # Link only immutable, unmodified assets. Generated config always gets a new file.
        replaced = {"data/gta.dat", "data/default.dat", *("data/" + name for name in environment)}
        replaced.update("data/script/" + name for name in scripts)
        if classic and game:
            # Run the cloned base with its own stock runtime libraries.
            for src in game.iterdir():
                if src.is_file() and (
                    src.name.lower() in ("gta_sa.exe", "stream.ini") or src.suffix.lower() == ".dll"
                ):
                    shutil.copyfile(src, root / src.name)
        for group in ("anim", "audio", "data", "models", "text", "movies") if game else ():
            for src in (game / group).rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(game)
                if rel.as_posix().lower() in replaced:
                    continue
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if classic and game:
                    shutil.copyfile(src, dst)
                    continue
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copyfile(src, dst)
        if scripts:
            target = root / "data/script"
            target.mkdir(parents=True, exist_ok=True)
            for name, payload in scripts.items():
                (target / name).write_bytes(payload)
        (root / "data").mkdir(exist_ok=True)
        for name in environment:
            shutil.copyfile(quarter / name, root / "data" / name)
        if packaged_route:
            shutil.copyfile(quarter / "route.json", root / "sphere-route.json")
        relative = Path("data/maps/sphere_native")
        patch = root / relative
        patch.mkdir(parents=True, exist_ok=False)
        collision = bind_collisions((quarter / "brquarter.col").read_bytes(), ids)
        collision_hash = write_game_img(
            quarter / "brquarter.img", patch / "brquarter.img", collision
        )
        (patch / "brquarter.ide").write_text(ide, encoding="ascii")
        (patch / "brquarter.ipl").write_text(ipl, encoding="ascii")
        additions = [
            r"IMG DATA\MAPS\SPHERE_NATIVE\BRQUARTER.IMG",
            r"IDE DATA\MAPS\SPHERE_NATIVE\BRQUARTER.IDE",
            r"IPL DATA\MAPS\SPHERE_NATIVE\BRQUARTER.IPL",
        ]
        if not game:
            (root / "sphere-map-fragment.dat").write_text(
                "\n".join(additions) + "\n", encoding="ascii"
            )
        else:
            for filename in ("default.dat", "gta.dat"):
                base = (game / "data" / filename).read_text(encoding="cp1252").splitlines()
                remaining = [line for line in base if not re.match(r"^\s*IPL\s+", line, re.I)]
                if filename == "gta.dat":
                    exit_at = next(
                        (i for i, line in enumerate(remaining) if line.strip().upper() == "EXIT"),
                        len(remaining),
                    )
                    remaining[exit_at:exit_at] = additions
                (root / "data" / filename).write_text(
                    "\n".join(remaining) + "\n", encoding="cp1252"
                )
        (root / "sphere-scenario.json").write_text(
            json.dumps(
                dict(
                    quarterRevision=proof["revision"],
                    routeSha256=packaged_route,
                    models=ids,
                    gameplayBasePresent=bool(game),
                    classicScenario=bool(classic),
                    sourceGameDirectory=str(game) if game else None,
                    mapManifestSha256=hashlib.sha256(
                        (quarter / "manifest.json").read_bytes()
                    ).hexdigest(),
                    streamedCollisionSha256=collision_hash,
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
    mode = cli.add_mutually_exclusive_group(required=True)
    mode.add_argument("--game", type=Path)
    mode.add_argument(
        "--map-only", action="store_true", help="prepare a map without a gameplay base"
    )
    cli.add_argument(
        "--classic-scenario", type=Path, help="compiled main.scm for the original PC game"
    )
    for key in ("quarter", "output"):
        cli.add_argument("--" + key, required=True, type=Path)
    args = cli.parse_args()
    stage(args.game, args.quarter, args.output, args.classic_scenario)
