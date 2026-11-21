"""Capture native model residency at selected original camera positions in an isolated game."""

import argparse
import json
import math
import shutil
import sqlite3
import subprocess
from pathlib import Path

import numpy as np

from scripts.pilot.world_map_lab.check_rendered_surfaces import ExteriorScene
from scripts.pilot.world_map_lab.inspect_world_cells import capture, mission
from scripts.pilot.world_map_lab.run_world_map_suite import game_server, stage_assets


def targets(database, game, sites, probes):
    ids = {}
    ide = game / "data/maps/brworld/brworld.ide"
    for row in ide.read_text(encoding="ascii").splitlines():
        parts = row.split(",")
        if len(parts) >= 4 and parts[0].strip().isdigit():
            ids[parts[1].strip().lower()] = int(parts[0])
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        scene = ExteriorScene(db)
        groups = []
        expected = []
        for site in sites:
            x, y, z = site["ground"]
            names = db.execute(
                "select distinct m.name from spatial s join instance i using(id) "
                "join model m on m.id=i.model where s.minx<? and s.maxx>? "
                "and s.miny<? and s.maxy>? and s.minz<? and s.maxz>?",
                (x + 12, x - 12, y + 12, y - 12, z + 3, z - 5),
            )
            groups.append({name: ids[name] for (name,) in names if name in ids})
            rays = []
            eye = np.array(site["eye"])
            forward = np.asarray(site["target"]) - eye
            forward /= np.linalg.norm(forward)
            right = np.cross(forward, [0, 0, 1])
            right /= np.linalg.norm(right)
            up = np.cross(right, forward)
            # The fixed survey camera uses a 70-degree horizontal field of view at 16:9.
            tangent = math.tan(math.radians(35))
            for u, v in probes:
                if not (0 <= u <= 1 and 0 <= v <= 1):
                    raise ValueError("ray coordinates must be fractions of the frame")
                direction = (
                    forward + (2 * u - 1) * tangent * right - (2 * v - 1) * tangent * (9 / 16) * up
                )
                hit = scene.first_hit(eye, direction / np.linalg.norm(direction), 1250)
                rays.append({"uv": [u, v], "source": hit})
                if hit and hit["model"] in ids:
                    groups[-1][hit["model"]] = ids[hit["model"]]
            expected.append(rays)
    return groups, expected


def run(args):
    plan = json.loads(args.plan.read_bytes())["sites"]
    sites = [plan[i] for i in args.site]
    groups, expected = targets(args.database, args.game, sites, args.ray)
    args.output.mkdir(parents=True, exist_ok=False)
    web = args.output / "web"
    shutil.copytree(args.web, web, ignore=shutil.ignore_patterns("inspection"))
    worker = web / "worker.js"
    text = worker.read_text(encoding="utf8")
    anchor = "    linearMemoryMiB: wasm?.memory?.buffer.byteLength / 1048576,"
    if text.count(anchor) != 1:
        raise ValueError("unexpected telemetry layout")
    ids = sorted({ident for group in groups for ident in group.values()})
    probe = Path(__file__).with_name("native_surface_probe.js").read_text(encoding="utf8")
    text = text.replace(
        anchor,
        anchor + "\n    renderProbe: inspectNativeSurfaces(wasm, state, " + json.dumps(ids) + "),",
    )
    worker.write_text(text + "\n" + probe, encoding="utf8")
    scripts = stage_assets(args.game, args.output / "game")
    source = mission(args.scenario.read_text(encoding="ascii"), sites).replace(
        "WAIT 2450", "WAIT 5500"
    )
    (scripts / "main.sc").write_text(source, encoding="ascii")
    subprocess.run(
        [
            str(args.compiler.resolve()),
            "compile",
            "--config=gtasa",
            "--guesser",
            "main.sc",
            "-o",
            "main.scm",
        ],
        cwd=scripts,
        check=True,
    )
    (args.output / "targets.json").write_text(
        json.dumps(dict(zip(args.site, groups, strict=True)), indent=2), encoding="utf8"
    )
    (args.output / "expected-rays.json").write_text(json.dumps(expected, indent=2), encoding="utf8")
    (args.output / "plan.json").write_text(json.dumps({"sites": sites}, indent=2), encoding="utf8")
    with game_server(
        args.server, web, args.output / "game", args.mods, args.output / "server.log"
    ) as url:
        return capture(url, {"sites": sites}, args.output / "frames", args.chrome)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "database",
        "game",
        "plan",
        "web",
        "output",
        "server",
        "mods",
        "compiler",
        "scenario",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--ray", action="append", nargs=2, type=float, default=[], metavar=("U", "V")
    )
    parser.add_argument("--site", type=int, nargs="+", required=True)
    parser.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    stats = run(parser.parse_args())
    print(stats)
    raise SystemExit(int(bool(stats["missing"] or stats["engineError"] or stats["ioFailures"])))
