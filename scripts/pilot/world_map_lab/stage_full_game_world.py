"""Compose a verified full-world overlay with an isolated clean classic GTA SA installation."""

import argparse
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.world_map_lab.audit_game_runtime import inspect_runtime
from scripts.pilot.world_map_lab.export_full_game_world import definitions, digest, source_file
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


def stage(game, world, destination, scenario):
    game, world = game.resolve(strict=True), world.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or any(destination.is_relative_to(p) for p in (world, game)):
        raise ValueError("choose a new directory outside both inputs")
    manifest = json.loads((world / "world-manifest.json").read_bytes())
    if manifest.get("scope") != "all-active-source-scenes":
        raise ValueError("full-world manifest required")
    scripts = json.loads((scenario / "classic-scenario.json").read_bytes())
    if not manifest["routeSha256"] or manifest["routeSha256"] != scripts["routeSha256"]:
        raise ValueError("world and compiled scenario belong to different routes")
    missing = [
        p
        for p, present in inspect_runtime(game).items()
        if not present and p != "data/script/main.scm"
    ]
    missing.extend(n for n in ("gta_sa.exe", "models/player.img") if not (game / n).is_file())
    if missing:
        raise ValueError("missing classic gameplay files: " + ", ".join(missing))
    map_dir = "data/maps/brworld/"
    ids, _, _ = definitions(world / map_dir / "brworld.ide")
    occupied = base_ids(game) & set(ids.values())
    if occupied:
        raise ValueError(
            f"base IDE still occupies {len(occupied)} world IDs, first {min(occupied)}; "
            "use a cleaned total-conversion base"
        )
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
    # Keep the base scripts, DLLs, adjuster configuration and gameplay assets in the clone.
    # Only the two new script binaries, environment and map directives are replaced.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temp:
        root = Path(temp) / "game"
        shutil.copytree(game, root)
        for rel, checksum in expected.items():
            src = source_file(world, rel)
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                raise ValueError("overlay path outside destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            if digest(target) != checksum:
                raise ValueError(f"overlay checksum mismatch: {rel}")
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
    args = parser.parse_args()
    stage(args.game, args.world, args.output, args.classic_scenario)
