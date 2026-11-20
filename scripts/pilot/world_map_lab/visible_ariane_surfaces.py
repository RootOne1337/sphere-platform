"""Project semantic surfaces in height order and hide them behind the sampled visible scene."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from scripts.pilot.world_map_lab.build_ariane_atlas import ROAD_COLORS, preview, read_matching_image
from scripts.pilot.world_map_lab.collect_ariane_nav_geometry import HEADER
from scripts.pilot.world_map_lab.render_ariane_world import View, pack_textures, render
from scripts.pilot.world_map_lab.world_navmesh import checksum


def visible(folder, atlas, lanes):
    from numba import njit

    meta = json.loads((atlas / "ariane-world-render.json").read_bytes())
    source = json.loads((folder / "geometry.json").read_bytes())
    if (
        meta["placementRevision"] != source["placementRevision"]
        or lanes["worldId"] != meta["worldId"]
    ):
        raise ValueError("mismatched source atlas")
    base = read_matching_image(atlas / "ariane-world-top.png", meta["views"]["top"]["sha256"])
    view = View(meta["bounds"], base.width)
    raster = njit(cache=True)(render)
    data = np.memmap(folder / "world-geometry.bin", dtype="u1", mode="r")
    b = meta["bounds"]
    colors = [np.array([[[i + 1, 0, 0, 255]]], np.uint8) for i in range(3)]
    tex = pack_textures(colors)
    cursor = 8
    while cursor < len(data):
        kind, n, x0, y0, x1, y1 = HEADER.unpack_from(data, cursor)
        cursor += HEADER.size
        if (
            kind in (3, 4, 5)
            and x0 <= b["right"]
            and x1 >= b["left"]
            and y0 <= b["top"]
            and y1 >= b["bottom"]
        ):
            xyz = np.ndarray((n, 3, 3), "<f4", data, cursor)
            norms = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
            xyz = xyz[np.abs(norms[:, 2]) >= 0.82 * np.linalg.norm(norms, axis=1)]
            if len(xyz):
                view.draw(
                    raster,
                    xyz,
                    np.zeros((len(xyz), 3, 2), np.float32),
                    np.ones(len(xyz), np.float32),
                    np.full(len(xyz), kind - 3, np.int64),
                    tex,
                )
        cursor += n * 36
    precise = atlas / "ariane-world-visible-height.npz"
    if precise.is_file() and meta.get("streetHeightBand"):
        with np.load(precise, allow_pickle=False) as h:
            upper = h["height"]
        if upper.shape != view.depth.shape:
            raise ValueError("visible-scene depth has incorrect dimensions")
        stride, tolerance = 1, 0.08
    else:
        with np.load(atlas / "ariane-world-heightfield.npz", allow_pickle=False) as h:
            elevations = h["height"]
        ix = np.minimum((np.arange(base.width) + 1) // 3, elevations.shape[1] - 1)
        iy = np.minimum((np.arange(base.height) + 1) // 3, elevations.shape[0] - 1)
        upper = elevations[iy[:, None], ix]
        stride, tolerance = 3, 0.65
    candidate = np.isfinite(view.depth)
    visible = candidate & np.isfinite(upper) & (-view.depth >= upper - tolerance)
    ink = np.zeros((base.height, base.width, 4), np.uint8)
    for idx, (_, rgba) in enumerate(ROAD_COLORS):
        ink[visible & (view.image[:, :, 0] == idx + 1)] = rgba
    overlay = Image.fromarray(ink)
    draw = ImageDraw.Draw(overlay)
    for lane in lanes["lanes"]:
        line = [
            ((x - b["left"]) * view.scale, (b["top"] - y) * view.scale)
            for x, y, *_ in lane["points"]
        ]
        draw.line(line, fill=(182, 255, 230, 255), width=3)
    overlay.save(atlas / "ariane-world-road-overlay.png")
    merged = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    merged.save(atlas / "ariane-world-map-with-roads.png")
    preview(merged, atlas / "ariane-world-map-preview.jpg")
    return {
        "extent": meta.get("area") or "world",
        "overlaySha256": checksum(atlas / "ariane-world-road-overlay.png"),
        "projectedPixels": int(candidate.sum()),
        "visiblePixels": int(visible.sum()),
        "depthPixelStride": stride,
        "heightTolerance": tolerance,
        "geometrySha256": source["geometrySha256"],
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--folder", type=Path, required=True)
    p.add_argument("--lane-report", type=Path, required=True)
    args = p.parse_args()
    if (
        checksum(args.folder / "world-geometry.bin")
        != json.loads((args.folder / "geometry.json").read_bytes())["geometrySha256"]
    ):
        raise ValueError("geometry hash mismatch")
    lanes = json.loads(args.lane_report.read_bytes())
    atlas = args.folder / "atlas"
    reports = [
        visible(args.folder, location, lanes)
        for location in (atlas, atlas / "batyrevo", atlas / "uzhny")
    ]
    (atlas / "visible-streets.json").write_text(
        json.dumps(reports, indent=2) + "\n", encoding="utf-8"
    )
    print(reports)
