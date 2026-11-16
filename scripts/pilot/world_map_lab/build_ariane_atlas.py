"""Package the textured world map, road overlay and interactive elevation preview."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from scripts.pilot.world_map_lab.ariane_geometry import REGIONS

DETAIL_AREAS = ("batyrevo", "uzhny")
AREA_LABELS = {"batyrevo": "Батырево", "uzhny": "Южный"}
TEMPLATE = Path(__file__).with_name("world_atlas.html")
ROAD_COLORS = (
    ((83, 184, 177), (104, 216, 239, 192)),
    ((221, 163, 103), (255, 187, 116, 183)),
    ((211, 154, 205), (230, 161, 218, 188)),
)


def read_matching_image(path, expected):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError(f"{path.name} does not match its source manifest")
    with Image.open(path) as image:
        return image.convert("RGB")


def road_overlay(roads, lanes, size, bounds):
    source = np.asarray(roads)
    ink = np.zeros((*source.shape[:2], 4), dtype=np.uint8)
    for original, color in ROAD_COLORS:
        ink[(source == original).all(axis=2)] = color
    image = Image.fromarray(ink).resize(size, Image.Resampling.NEAREST)
    dx = image.width / (bounds["right"] - bounds["left"])
    dy = image.height / (bounds["top"] - bounds["bottom"])

    def pixel(xyz):
        return ((xyz[0] - bounds["left"]) * dx, (bounds["top"] - xyz[1]) * dy)

    draw = ImageDraw.Draw(image)
    for lane in lanes["lanes"]:
        line = [pixel(xyz) for xyz in lane["points"]]
        draw.line(line, fill=(14, 45, 38, 255), width=7)
        draw.line(line, fill=(182, 255, 230, 255), width=4)
    return image


def height_payload(path, bounds, size):
    with np.load(path, allow_pickle=False) as dataset:
        depth = dataset["height"][::2, ::2]
        rgb = dataset["rgb"][::2, ::2]
    height, width = depth.shape
    if (height, width) != tuple((length + 5) // 6 for length in size[::-1]):
        raise ValueError("height grid does not match the world image")
    valid = np.isfinite(depth)
    if valid.mean() < 0.15 or depth[valid].min() <= -511.95 or depth[valid].max() >= 2764.75:
        raise ValueError("invalid atlas height field domain")
    raw = np.zeros((*depth.shape, 5), dtype=np.uint8)
    packed = np.round((depth[valid] + 512) / 0.05).astype("<u2")
    raw[:, :, :2][valid] = packed.view("u1").reshape(-1, 2)
    raw[:, :, 2:] = rgb
    xstep = (bounds["right"] - bounds["left"]) / size[0]
    ystep = (bounds["top"] - bounds["bottom"]) / size[1]
    grid = {
        "width": width,
        "height": height,
        "x": bounds["left"] + xstep / 2,
        "y": bounds["top"] - ystep / 2,
        "dx": xstep * 6,
        "dy": ystep * 6,
    }
    return grid, base64.b64encode(raw.tobytes()).decode("ascii")


def preview(image, path):
    small = image.copy()
    small.thumbnail((1700, 1640), Image.Resampling.LANCZOS)
    small.convert("RGB").save(path, quality=92, optimize=True)


def build(output, road_report, lane_report):
    meta = json.loads((output / "ariane-world-render.json").read_bytes())
    road = json.loads(road_report.read_bytes())
    lanes = json.loads(lane_report.read_bytes())
    if (
        meta["bounds"] != road["bounds"]
        or meta["worldId"] != road["worldId"]
        or meta["placementRevision"] != road["placementRevision"]
        or meta["worldId"] != lanes["worldId"]
    ):
        raise ValueError("atlas sources do not refer to the same world")
    source = read_matching_image(road_report.with_suffix(".png"), road["imageSha256"])
    top = read_matching_image(output / "ariane-world-top.png", meta["views"]["top"]["sha256"])
    render = read_matching_image(
        output / "ariane-world-color-3d.png", meta["views"]["color-3d"]["sha256"]
    )
    overlay = road_overlay(source, lanes, top.size, meta["bounds"])
    overlay.save(output / "ariane-world-road-overlay.png", compress_level=6)
    merged = Image.alpha_composite(top.convert("RGBA"), overlay)
    merged.convert("RGB").save(output / "ariane-world-map-with-roads.png", compress_level=4)
    preview(merged, output / "ariane-world-map-preview.jpg")
    preview(render, output / "ariane-world-3d-preview.jpg")

    area = meta.get("area")
    details = {}
    if area is None:
        for region in DETAIL_AREAS:
            if not (output / region / "ariane-world-map.html").is_file():
                continue
            details[region] = {"bounds": REGIONS[region], "path": region + "/"}
    grid, raw = height_payload(output / "ariane-world-heightfield.npz", meta["bounds"], top.size)
    template = TEMPLATE.read_text(encoding="utf-8-sig")
    for view, filename in (("top", "ariane-world-map.html"), ("3d", "ariane-world-3d.html")):
        html = template.replace("__TERRAIN__", raw if view == "3d" else "").replace(
            "__METADATA__",
            json.dumps(
                {
                    "view": view,
                    "bounds": meta["bounds"],
                    "grid": grid,
                    "areas": {} if area else {**REGIONS, "kremlin": [-3000, -2750, 2390, 2660]},
                    "area": area,
                    "areaName": AREA_LABELS.get(area, area),
                    "details": details,
                },
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
        (output / filename).write_text(html + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "worldId": meta["worldId"],
                "top": top.size,
                "render": render.size,
                "interactiveGrid": grid,
            }
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--road-report", required=True, type=Path)
    parser.add_argument("--lane-report", required=True, type=Path)
    args = parser.parse_args()
    build(args.output, args.road_report, args.lane_report)


if __name__ == "__main__":
    main()
