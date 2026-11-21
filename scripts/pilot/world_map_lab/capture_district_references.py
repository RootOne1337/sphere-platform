"""Capture a stationary source-map grid for cold localization without recording a drive."""

import argparse
import json
import math
import subprocess
from pathlib import Path

from scripts.pilot.world_map_lab.bake_game_reference_views import camera_mission
from scripts.pilot.world_map_lab.check_destination_district import grid_sites
from scripts.pilot.world_map_lab.export_full_game_world import digest
from scripts.pilot.world_map_lab.inspect_world_cells import capture
from scripts.pilot.world_map_lab.live_destination import RoadMap
from scripts.pilot.world_map_lab.run_world_map_suite import game_server, stage_assets


def build(args):
    game = args.game.resolve()
    road = RoadMap(args.planner)
    revision = road.meta["placementRevision"]
    if json.loads((game / "sphere-route.json").read_bytes())["revision"] != revision:
        raise ValueError("game and road planner use different map revisions")
    if not 1 <= args.step <= 12 or args.heading_step <= 0 or 360 % args.heading_step:
        raise ValueError("invalid camera grid")
    sites = []
    for x, y, z in grid_sites(road, args.bounds, args.step, ("drive", "walk")):
        for angle in range(0, 360, args.heading_step):
            yaw = math.radians(angle + args.heading_offset)
            sites.append(
                dict(
                    referenceIndex=len(sites),
                    cell=[math.floor(x / 512), math.floor(y / 512)],
                    ground=[x, y, z - 1.45],
                    eye=[x, y, z],
                    target=[x + 8 * math.cos(yaw), y + 8 * math.sin(yaw), z - 0.36],
                )
            )
    if not sites:
        raise ValueError("no navigable surfaces in the selected district")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    script = stage_assets(game, out / "inspection-game")
    source = args.scenario.read_text(encoding="ascii")
    (script / "main.sc").write_text(camera_mission(source, sites), encoding="ascii")
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
        cwd=script,
        check=True,
    )
    with game_server(
        args.server, args.web, out / "inspection-game", args.mods, out / "server.log"
    ) as url:
        stats = capture(url, dict(sites=sites), out / "frames", args.chrome)
    if stats["missing"] or stats["engineError"] or stats["flatFrames"] or stats["ioFailures"]:
        raise ValueError(f"incomplete reference capture: {stats}")
    manifest = dict(
        revision=revision,
        step=args.step,
        bounds=args.bounds,
        headingStep=args.heading_step,
        headingOffset=args.heading_offset,
        views=len(sites),
        samplesSha256=digest(out / "frames/samples.json"),
        placementSha256=digest(game / "sphere-world-cells.json"),
    )
    (out / "frames/survey.json").write_text(json.dumps(manifest), encoding="utf8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("game", "mods", "scenario", "web", "compiler", "server", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--bounds", nargs=4, type=int, required=True)
    parser.add_argument("--step", type=int, default=6)
    parser.add_argument("--heading-step", type=int, default=45)
    parser.add_argument("--heading-offset", type=float, default=0)
    parser.add_argument("--planner", default="http://127.0.0.1:8817")
    parser.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    build(parser.parse_args())
