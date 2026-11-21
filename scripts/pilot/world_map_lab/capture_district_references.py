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


def road_sites(road, endpoints, step):
    """Sample a planned lane in world units, keeping both endpoints and local bearing."""
    start, end = endpoints[:3], endpoints[3:]
    route = road.route(start, end)
    path = route.get("path", [])
    if (
        route.get("status") != "complete"
        or len(path) < 2
        or math.dist(path[0], start) > 2.5
        or math.dist(path[-1], end) > 2.5
    ):
        raise ValueError("no continuous road between the survey endpoints")
    distance = 0.0
    next_sample = 0.0
    last_bearing = None
    for a, b in zip(path, path[1:]):
        length = math.dist(a, b)
        if length < 1e-5:
            continue
        last_bearing = math.atan2(b[1] - a[1], b[0] - a[0])
        while next_sample < distance + length:
            fraction = (next_sample - distance) / length
            x, y, z = (u + (v - u) * fraction for u, v in zip(a, b))
            yield x, y, z + 1.45, last_bearing
            next_sample += step
        distance += length
    if last_bearing is None:
        raise ValueError("road survey has no length")
    x, y, z = path[-1]
    yield x, y, z + 1.45, last_bearing


def build(args):
    game = args.game.resolve()
    road = RoadMap(args.planner)
    revision = road.meta["placementRevision"]
    if json.loads((game / "sphere-route.json").read_bytes())["revision"] != revision:
        raise ValueError("game and road planner use different map revisions")
    if not 1 <= args.step <= 12 or args.heading_step <= 0 or 360 % args.heading_step:
        raise ValueError("invalid camera grid")
    sites = []
    if args.road_endpoints:
        cameras = road_sites(road, args.road_endpoints, args.step)
    else:
        cameras = (
            (*site, 0.0) for site in grid_sites(road, args.bounds, args.step, ("drive", "walk"))
        )
    for x, y, z, bearing in cameras:
        for angle in range(0, 360, args.heading_step):
            yaw = bearing + math.radians(angle + args.heading_offset)
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
        roadEndpoints=args.road_endpoints,
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
    area = parser.add_mutually_exclusive_group(required=True)
    area.add_argument("--bounds", nargs=4, type=int)
    area.add_argument("--road-endpoints", nargs=6, type=float)
    parser.add_argument("--step", type=int, default=6)
    parser.add_argument("--heading-step", type=int, default=45)
    parser.add_argument("--heading-offset", type=float, default=0)
    parser.add_argument("--planner", default="http://127.0.0.1:8817")
    parser.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    build(parser.parse_args())
