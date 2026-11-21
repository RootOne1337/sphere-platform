"""Compose a verified full-world overlay with an isolated classic GTA SA installation."""

import argparse
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.audit_game_runtime import inspect_runtime
from scripts.pilot.world_map_lab.classic_world_binding import bind_world
from scripts.pilot.world_map_lab.classic_world_limits import CONFIG_NAME, merge_limits, requirements
from scripts.pilot.world_map_lab.export_full_game_world import digest, source_file
from scripts.pilot.world_map_lab.stage_game_quarter import base_ids, directives


def merge_layout(path, additions=()):
    lines = []
    for raw in path.read_text(encoding="cp1252").splitlines():
        fields = raw.partition("#")[0].split()
        if fields and fields[0].upper() == "IPL":
            continue
        if fields and fields[0].upper() == "EXIT":
            break
        lines.append(raw)
    lines.extend(additions)
    lines.append("EXIT")
    return "\n".join(lines) + "\n"


def stage(game, world, destination, scenario, *, browser=False):
    game, world = game.resolve(strict=True), world.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or any(destination.is_relative_to(p) for p in (world, game)):
        raise ValueError("choose a new directory outside both inputs")
    manifest = json.loads((world / "world-manifest.json").read_bytes())
    if manifest.get("scope") != "all-active-source-scenes":
        raise ValueError("full-world manifest required")
    scenario = scenario.resolve(strict=True)
    scripts = json.loads((scenario / "classic-scenario.json").read_bytes())
    if "worldManifestSha256" in scripts:
        if scripts["worldManifestSha256"] != digest(world / "world-manifest.json"):
            raise ValueError("scenario was compiled for another world")
        itinerary = source_file(scenario, "sphere-route.json")
        if digest(itinerary) != scripts["routeSha256"]:
            raise ValueError("compiled itinerary checksum mismatch")
    elif manifest["routeSha256"] and manifest["routeSha256"] == scripts["routeSha256"]:
        itinerary = source_file(world, "sphere-route.json")
    else:
        raise ValueError("world and compiled scenario belong to different routes")
    missing = [
        p
        for p, present in inspect_runtime(game).items()
        if not present and p != "data/script/main.scm"
    ]
    required = ("models/player.img",) if browser else ("gta_sa.exe", "models/player.img")
    missing.extend(n for n in required if not (game / n).is_file())
    if missing:
        raise ValueError("missing classic gameplay files: " + ", ".join(missing))
    map_dir = "data/maps/brworld/"
    occupied = base_ids(game)
    if (game / map_dir).exists():
        raise ValueError("base already contains a Black Russia conversion")
    if any(p.is_symlink() or p.is_junction() for p in game.rglob("*")):
        raise ValueError("base contains a link; select a standalone game directory")
    expected = {map_dir + a["name"]: a["sha256"] for a in manifest["archives"]}
    expected[map_dir + "brworld.ide"] = manifest["ideSha256"]
    expected.update({map_dir + s["packaged"]: s["sha256"] for s in manifest["scenes"]})
    expected.update({"data/" + n: manifest["environment"][n] for n in ("water.dat", "timecyc.dat")})
    expected.update({"data/script/" + n: scripts["files"][n] for n in ("main.scm", "script.img")})
    expected["sphere-route.json"] = scripts["routeSha256"]
    additions = ["IMG " + (map_dir + a["name"]).replace("/", "\\") for a in manifest["archives"]]
    additions.append(r"IDE data\maps\brworld\brworld.ide")
    additions.extend(
        "IPL " + (map_dir + s["packaged"]).replace("/", "\\") for s in manifest["scenes"]
    )
    wanted = [a.replace("\\", "/").lower() for a in additions]
    if [f"{k} {v}".lower() for k, v in directives(world / "world-fragment.dat")] != wanted:
        raise ValueError("map directives differ from manifest")
    # All changes, including model bindings and the capacity profile, belong to the clone.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        root = Path(temp) / "game"
        if browser:
            root.mkdir()
            for name in ("anim", "audio", "data", "models", "movies", "text"):
                if (game / name).is_dir():
                    shutil.copytree(game / name, root / name)
            if (game / "stream.ini").is_file():
                shutil.copyfile(game / "stream.ini", root / "stream.ini")
        else:
            shutil.copytree(game, root)
        for rel, checksum in expected.items():
            if rel == "sphere-route.json":
                src = itinerary
            elif rel.startswith("data/script/"):
                src = source_file(scenario, Path(rel).name)
            else:
                src = source_file(world, rel)
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                raise ValueError("overlay path outside destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            if digest(target) != checksum:
                raise ValueError(f"overlay checksum mismatch: {rel}")
        binding = bind_world(root / map_dir, manifest, occupied)
        archives = {
            value.lower()
            for dat in ("default.dat", "gta.dat")
            for kind, value in directives(game / "data" / dat)
            if kind == "IMG"
        }
        needed = requirements(
            manifest,
            max(max(occupied), binding["highestModelId"]),
            root / map_dir / "brworld.ide",
            root / "data/water.dat",
            len(archives),
        )
        config = root / CONFIG_NAME
        if browser:
            runtime_fields = {"runtime": "browser-wasm", "requiredWorldLimits": needed}
        else:
            existing = config.read_text(encoding="cp1252") if config.is_file() else ""
            config.write_text(merge_limits(existing, needed), encoding="cp1252")
            runtime_fields = {
                "gameExecutableSha256": digest(root / "gta_sa.exe"),
                "limitsFile": CONFIG_NAME,
                "limitsSha256": digest(config),
                "limitAdjusterPresent": (root / "$fastman92limitAdjuster.asi").is_file(),
            }
        for name in ("default.dat", "gta.dat"):
            path = Path("data") / name
            content = merge_layout(game / path, additions if name == "gta.dat" else ())
            (root / path).write_text(content, encoding="cp1252")
        (root / "sphere-full-world.json").write_text(
            json.dumps(
                {
                    "worldManifestSha256": digest(world / "world-manifest.json"),
                    "routeSha256": scripts["routeSha256"],
                    "additionalImageArchives": len(manifest["archives"]),
                    "largestSceneInstances": max(s["instances"] for s in manifest["scenes"]),
                    "sourceGameDirectory": str(game),
                    **runtime_fields,
                    "scenarioFiles": {
                        n: digest(root / "data/script" / n) for n in ("main.scm", "script.img")
                    },
                    "layoutSha256": {
                        n: digest(root / "data" / n) for n in ("default.dat", "gta.dat")
                    },
                    "binding": binding,
                    "gameplayVerified": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        root.rename(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "world", "output", "classic-scenario"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--browser", action="store_true", help="stage data for the WebAssembly game"
    )
    args = parser.parse_args()
    stage(args.game, args.world, args.output, args.classic_scenario, browser=args.browser)
