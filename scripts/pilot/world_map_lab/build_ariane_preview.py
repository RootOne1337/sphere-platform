"""Build the standalone A/B planning preview from the inspected Ariane district tile."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.pilot.world_map_lab.audit_ariane_surface_coverage import REGIONS

HERE = Path(__file__).resolve().parent
EXAMPLE = [[-2915.0, 2412.0], [-2867.0, 2645.0]]


def encode(array):
    return base64.b64encode(array.tobytes()).decode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build_tile(grid_path, raster_path, orthomap_path, mode="drive"):
    grid_file = grid_path.read_bytes()
    raw_grid = json.loads(grid_file)
    grid = raw_grid["grid"]
    shape = (grid["height"], grid["width"])
    raster_bytes = raster_path.read_bytes()
    with np.load(raster_path, allow_pickle=False) as source:
        free = source["free"]
        clearance = source["clearance"]
        height = source["height"]
    expected_free = base64.b64decode(raw_grid["free_b64"], validate=True)
    if (
        free.shape != shape
        or clearance.shape != shape
        or height.shape != shape
        or free.dtype != bool
        or not free.any()
        or free.astype("u1").tobytes() != expected_free
    ):
        raise ValueError("surface layers do not match their grid manifest")
    if (
        not np.isfinite(height[free]).all()
        or not np.isfinite(clearance).all()
        or clearance.min() < 0
    ):
        raise ValueError("invalid geometry samples")
    minimum = raw_grid["horizontal_clearance"]
    if clearance[free].min() < minimum:
        raise ValueError("trusted drive grid includes an under-clearance cell")
    base_z = math.floor(float(height[free].min()))
    quantized_height = np.round((height[free] - base_z) * 100)
    if quantized_height.max() > 32767 or clearance.max() > 655.35:
        raise ValueError("surface exceeds raster encoding range")
    height_units = np.zeros(shape, dtype="<i2")
    height_units[free] = quantized_height.astype("<i2")
    clearance_units = np.floor(clearance * 100).astype("<u2")
    with Image.open(orthomap_path) as image:
        if (
            image.format != "JPEG"
            or image.size != (675, 960)
            or image.width * shape[0] != image.height * shape[1]
        ):
            raise ValueError("orthomap does not match the checked district grid")
    orthomap = orthomap_path.read_bytes()
    package = {
        "schema": "sphere.raster-surface.v1",
        "worldId": "black-russia-ariane",
        "areaId": "nizhny-kremlin",
        "mode": mode,
        "grid": {**grid, "baseZ": base_z},
        "minClearance": minimum,
        "maxGrade": 0.40,
        "sources": {
            "gridSha256": digest(grid_file),
            "rasterSha256": digest(raster_bytes),
            "orthomapSha256": digest(orthomap),
        },
        "free": encode(free.astype("u1")),
        "clearanceCentiUnits": encode(clearance_units),
        "heightCentiUnits": encode(height_units),
    }
    package["mapRevision"] = digest(
        json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
    )
    return package, orthomap


def inline_module(name, symbol):
    module = (HERE / name).read_text(encoding="utf-8")
    inline = module.removesuffix(f"\nexport {{{symbol}}};\n")
    if inline == module:
        raise ValueError(f"preview did not resolve {symbol} export")
    return inline


def script_json(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).replace("<", r"\u003c")


def load_overview(report_path, world_id):
    report = json.loads(report_path.read_bytes())
    image_path = report_path.with_suffix(".png")
    raw = image_path.read_bytes()
    bounds = report["bounds"]
    if (
        report["schema"] != "sphere.world-road-material-overview.v1"
        or report["worldId"] != world_id
        or report["imageSha256"] != digest(raw)
        or not all(math.isfinite(bounds[key]) for key in ("left", "right", "bottom", "top"))
        or not (bounds["left"] < bounds["right"] and bounds["bottom"] < bounds["top"])
    ):
        raise ValueError("world overview does not match its manifest")
    with Image.open(image_path) as image:
        if image.format != "PNG" or image.size != (report["imageWidth"], report["imageHeight"]):
            raise ValueError("unexpected world overview raster")
        image.verify()
    return {
        **{key: report[key] for key in ("bounds", "imageWidth", "imageHeight")},
        "image": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
        "layered": "layers" in report,
        "placementBounds": report.get("placementBounds", bounds),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--raster", required=True, type=Path)
    parser.add_argument("--orthomap", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", choices=("drive", "walk"), default="drive")
    parser.add_argument("--lanes", type=Path)
    parser.add_argument("--world-overview", type=Path)
    args = parser.parse_args()
    if args.mode == "walk" and args.lanes:
        parser.error("--lanes applies only to driving")
    tile, orthomap = build_tile(args.grid, args.raster, args.orthomap, args.mode)
    tile_json = script_json(tile)
    lanes = json.loads(args.lanes.read_bytes()) if args.lanes else None
    example = json.loads(args.grid.read_bytes())["example"] if args.mode == "walk" else EXAMPLE
    if lanes is not None:
        if (
            any(lanes[key] != tile[key] for key in ("worldId", "areaId", "mapRevision"))
            or lanes["orthomapSha256"] != tile["sources"]["orthomapSha256"]
        ):
            raise ValueError("lane preview does not match the district grid")
        points = lanes["lanes"][0]["points"]
        inset = max(0, (len(points) - 1) // 12)
        example = [points[inset][:2], points[-1 - inset][:2]]
    world = load_overview(args.world_overview, tile["worldId"]) if args.world_overview else None
    document = (HERE / "planner.html").read_text(encoding="utf-8")
    replacements = {
        "__PLANNER__": inline_module("world_grid.mjs", "createPlanner"),
        "__LANE_PLANNER__": inline_module("lane_preview.mjs", "createLanePlanner"),
        "__TILE__": tile_json,
        "__MAP__": base64.b64encode(orthomap).decode("ascii"),
        "__EXAMPLE__": script_json(example),
        "__LANES__": script_json(lanes),
        "__WORLD__": script_json(world),
        "__REGIONS__": script_json(
            {
                name: dict(zip(("left", "right", "bottom", "top"), bounds, strict=True))
                for name, bounds in REGIONS.items()
            }
        ),
    }
    for marker, value in replacements.items():
        if document.count(marker) != 1:
            raise ValueError(f"expected one {marker} placeholder")
        document = document.replace(marker, value)

    args.output.mkdir(parents=True, exist_ok=True)
    name = "ariane-world-lane-planner.html" if lanes else "ariane-kremlin-route-planner.html"
    surface = "ariane-kremlin-surface.json"
    if args.mode == "walk":
        name = "ariane-kremlin-footways-planner.html"
        surface = "ariane-kremlin-footways-surface.json"
    (args.output / surface).write_text(tile_json + "\n", encoding="utf-8")
    (args.output / name).write_text(document, encoding="utf-8")
    print(
        json.dumps(
            {"schema": tile["schema"], "mapRevision": tile["mapRevision"], "example": example}
        )
    )


if __name__ == "__main__":
    main()
