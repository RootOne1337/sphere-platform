"""Bind native browser RGB to the existing depth atlas at independently observed camera poses."""

import argparse
import json
import math
import shutil
import subprocess
import zlib
from pathlib import Path

import cv2
import numpy as np

from scripts.pilot.world_map_lab.export_full_game_world import digest
from scripts.pilot.world_map_lab.inspect_world_cells import capture
from scripts.pilot.world_map_lab.run_world_map_suite import game_server, stage_assets


def plan_views(views, walk_spacing, road_spacing, road_end):
    sites = []
    last = {}
    for i, view in enumerate(views):
        phase, station = view["phase"], view["s"]
        if phase == 1 and station > road_end:
            continue
        spacing = road_spacing if phase == 1 else walk_spacing
        if station != last.get(phase) and station - last.get(phase, -math.inf) < spacing:
            continue
        last[phase] = station
        x, y, z, yaw, pitch = view["pose"]
        front = np.array(
            [math.cos(yaw) * math.cos(pitch), math.sin(yaw) * math.cos(pitch), math.sin(pitch)]
        )
        sites.append(
            dict(
                referenceIndex=i,
                cell=[math.floor(x / 512), math.floor(y / 512)],
                ground=[x, y, z - 1.65],
                eye=[x, y, z],
                target=(np.array([x, y, z]) + 8 * front).tolist(),
            )
        )
    return sites


def camera_mission(base, sites):
    lines = [base[: base.index("camera_loop:")], "SET_CHAR_VISIBLE scplayer 0", "WAIT 500"]
    anchor = None
    for site in sites:
        x, y, z = site["eye"]
        if anchor is None or math.dist((x, y), anchor) > 30:
            lines.extend(
                [
                    f"REQUEST_COLLISION {x:.5f} {y:.5f}",
                    f"LOAD_SCENE {x:.5f} {y:.5f} {z:.5f}",
                    f"SET_CHAR_COORDINATES scplayer {x:.5f} {y:.5f} {z - 0.8:.5f}",
                    "WAIT 750",
                ]
            )
            anchor = x, y
        eye = " ".join(f"{v:.5f}" for v in site["eye"])
        target = " ".join(f"{v:.5f}" for v in site["target"])
        lines.extend(
            [
                f"SET_FIXED_CAMERA_POSITION {eye} 0.0 0.0 0.0",
                f"POINT_CAMERA_AT_POINT {target} 2",
                "WAIT 1350",
            ]
        )
    return "\n".join([*lines, "survey_end:", "WAIT 0", "GOTO survey_end", "}", ""])


def reproject_depth(depth, source_focal, target_focal):
    h, w = depth.shape
    y, x = np.indices((h, w), dtype=np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    scale = source_focal / target_focal
    return cv2.remap(depth, (x - cx) * scale + cx, (y - cy) * scale + cy, cv2.INTER_NEAREST)


def bake(args):
    out = args.output.resolve()
    meta = json.loads((args.bank / "index.json").read_bytes())
    route = args.game / "sphere-route.json"
    if meta["worldRevision"] != json.loads(route.read_bytes())["revision"] or meta[
        "routeSha256"
    ] != digest(route):
        raise ValueError("route and atlas do not match")
    for name in ("images.z", "xyz.f32", "sift.u8"):
        if digest(args.bank / name) != meta["files"][name]:
            raise ValueError(f"source atlas hash differs for {name}")
    if min(args.walk_spacing, args.road_spacing) <= 0 or args.road_end < 0:
        raise ValueError("invalid survey distance")
    sites = plan_views(meta["imageViews"], args.walk_spacing, args.road_spacing, args.road_end)
    out.mkdir(parents=True, exist_ok=False)
    scripts = stage_assets(args.game.resolve(), out / "inspection-game")
    source = camera_mission(args.scenario.read_text(), sites)
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
    with game_server(
        args.server, args.web, out / "inspection-game", args.mods, out / "server.log"
    ) as url:
        stats = capture(url, {"sites": sites}, out / "frames", args.chrome)
    if stats["missing"] or stats["engineError"] or stats["flatFrames"] or stats["ioFailures"]:
        raise ValueError(f"incomplete native reference survey: {stats}")
    samples = json.loads((out / "frames/samples.json").read_bytes())
    native = {site["referenceIndex"]: samples[str(i)] for i, site in enumerate(sites)}
    dest = out / "bank"
    dest.mkdir()
    for name in ("xyz.f32", "sift.u8"):
        shutil.copyfile(args.bank / name, dest / name)
    with (args.bank / "images.z").open("rb") as src, (dest / "images.z").open("xb") as dst:
        for i, view in enumerate(meta["imageViews"]):
            offset, length = view["bytes"]
            src.seek(offset)
            data = src.read(length)
            if i in native:
                sample = native[i]
                if not 35 <= sample["hfov"] <= 150:
                    raise ValueError("invalid surveyed field of view")
                raw = cv2.imread(str(out / "frames" / sample["file"]), cv2.IMREAD_GRAYSCALE)
                rgb = cv2.resize(raw, (320, 180), interpolation=cv2.INTER_AREA)
                depth = np.frombuffer(zlib.decompress(data), "<u2", offset=320 * 180).reshape(
                    180, 320
                )
                old = view.get("focalAt320", meta["focal"] * 320 / meta["size"][0])
                focal = 160 / math.tan(math.radians(sample["hfov"]) / 2)
                data = zlib.compress(
                    rgb.tobytes() + reproject_depth(depth, old, focal).tobytes(), 2
                )
                view["focalAt320"] = focal
            view["bytes"] = [dst.tell(), len(data)]
            dst.write(data)
    meta["files"]["images.z"] = digest(dest / "images.z")
    meta["nativeColorViews"] = sum("focalAt320" in v for v in meta["imageViews"])
    meta["nativeSurvey"] = dict(
        views=len(native),
        placementIndex=digest(args.game / "sphere-world-cells.json"),
        engine=digest(args.web / "pkg/sa_game_bg.wasm"),
        sourceBank=digest(args.bank / "index.json"),
    )
    (dest / "index.json").write_text(json.dumps(meta), encoding="utf8")
    print(json.dumps(meta["nativeSurvey"]))


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("bank", "game", "mods", "scenario", "web", "compiler", "server", "output"):
        cli.add_argument("--" + name, type=Path, required=True)
    cli.add_argument("--walk-spacing", type=float, default=4.2)
    cli.add_argument("--road-spacing", type=float, default=6)
    cli.add_argument("--road-end", type=float, default=math.inf)
    cli.add_argument("--chrome", default="C:/Program Files/Google/Chrome/Application/chrome.exe")
    bake(cli.parse_args())
