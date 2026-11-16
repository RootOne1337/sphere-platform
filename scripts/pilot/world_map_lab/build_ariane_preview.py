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

HERE = Path(__file__).resolve().parent
EXAMPLE = [[-2915.0, 2412.0], [-2867.0, 2645.0]]


def encode(array):
    return base64.b64encode(array.tobytes()).decode("ascii")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def build_tile(grid_path, raster_path, orthomap_path):
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
        "mode": "drive",
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--raster", required=True, type=Path)
    parser.add_argument("--orthomap", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    tile, orthomap = build_tile(args.grid, args.raster, args.orthomap)
    tile_json = json.dumps(tile, separators=(",", ":"))
    planner = (HERE / "world_grid.mjs").read_text(encoding="utf-8")
    inline = planner.removesuffix("\nexport {createPlanner};\n")
    if inline == planner:
        raise ValueError("preview bundle did not resolve planner export")
    document = (HERE / "planner.html").read_text(encoding="utf-8")
    document = (
        document.replace("__PLANNER__", inline)
        .replace("__TILE__", tile_json)
        .replace("__MAP__", base64.b64encode(orthomap).decode("ascii"))
        .replace("__EXAMPLE__", json.dumps(EXAMPLE))
    )
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "ariane-kremlin-surface.json").write_text(tile_json + "\n", encoding="utf-8")
    (args.output / "ariane-kremlin-route-planner.html").write_text(document, encoding="utf-8")
    print(
        json.dumps(
            {"schema": tile["schema"], "mapRevision": tile["mapRevision"], "example": EXAMPLE}
        )
    )


if __name__ == "__main__":
    main()
