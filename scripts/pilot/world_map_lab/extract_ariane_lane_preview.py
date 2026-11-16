"""Measure a marked road segment in the source Ariane orthomap."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter1d, map_coordinates

# The surveyed window ends before the nearest intersections in the source view.
Y_MIN, Y_MAX, Y_REFERENCE = 2458.0, 2557.5, 2508.0
SEPARATOR_SEEDS = (-2918.0, -2913.0, -2908.0)
SOURCE_BUFFER = 0.65


def paint_evidence(gray, grid):
    height, width = gray.shape
    x_scale = width / (grid["width"] * grid["step"])
    y_scale = height / (grid["height"] * grid["step"])
    ridge = np.clip(gray - gaussian_filter1d(gray, 2.2, axis=1), 0.0, 75.0)
    ys = np.arange(Y_MIN, Y_MAX + 0.01, 0.25)
    image_rows = (grid["top"] - ys) * y_scale - 0.5
    train = np.floor((ys - Y_MIN) / 7.25) % 3 != 2

    def sample(x_center, slope, lateral=0.0):
        x = x_center + slope * (ys - Y_REFERENCE) + lateral
        cols = (x - grid["left"]) * x_scale - 0.5
        return map_coordinates(ridge, [image_rows, cols], order=1, prefilter=False)

    results = []
    for seed in SEPARATOR_SEEDS:
        poses = (
            (float(shift), float(slope))
            for slope in np.arange(0.026, 0.056, 0.001)
            for shift in seed + np.arange(-1.2, 1.21, 0.05)
        )
        x, slope = max(poses, key=lambda params: sample(*params)[train].mean())
        values = sample(x, slope)[~train]
        flank = max(sample(x, slope, off)[~train].mean() for off in (-SOURCE_BUFFER, SOURCE_BUFFER))
        ratio = float(values.mean() / max(0.5, flank))
        hits = float(np.mean(values > 15.0))
        if values.mean() < 8.0 or ratio < 2.4 or hits < 0.10:
            raise ValueError("separator does not have independent paint support")
        results.append(
            {
                "ends": [[x + slope * (y - Y_REFERENCE), y] for y in (Y_MIN, Y_MAX)],
                "paint_mean": round(float(values.mean()), 2),
                "off_paint_mean": round(float(flank), 2),
                "paint_ratio": round(ratio, 2),
                "strong_sample_fraction": round(hits, 3),
            }
        )
    return results


def lane_centers(separators, surface):
    grid = surface["grid"]
    cols = grid["width"]
    rows = grid["height"]
    free = np.frombuffer(base64.b64decode(surface["free"], validate=True), dtype="u1").reshape(
        rows, cols
    )
    clearance = (
        np.frombuffer(
            base64.b64decode(surface["clearanceCentiUnits"], validate=True), dtype="<u2"
        ).reshape(rows, cols)
        / 100
    )
    elevation = (
        np.frombuffer(
            base64.b64decode(surface["heightCentiUnits"], validate=True), dtype="<i2"
        ).reshape(rows, cols)
        / 100
        + grid["baseZ"]
    )
    ys = np.arange(Y_MIN, Y_MAX + 0.01, 0.25)
    fraction = (ys - Y_MIN) / (Y_MAX - Y_MIN)
    results = []
    for index, (first, second) in enumerate(zip(separators, separators[1:]), 1):
        a = np.array(first["ends"])[:, 0]
        b = np.array(second["ends"])[:, 0]
        width = np.interp(fraction, [0, 1], b - a)
        xs = np.interp(fraction, [0, 1], (a + b) / 2)
        clearance_to_paint = float(width.min() / 2)
        ii = np.floor((grid["top"] - ys) / grid["step"]).astype(int)
        jj = np.floor((xs - grid["left"]) / grid["step"]).astype(int)
        if (
            ii.min() < 0
            or ii.max() >= rows
            or jj.min() < 0
            or jj.max() >= cols
            or clearance_to_paint < surface["minClearance"]
            or not np.all(free[ii, jj] == 1)
            or clearance[ii, jj].min() < surface["minClearance"]
        ):
            raise ValueError(f"lane center crosses a boundary or leaves inspected road: {index}")
        z = elevation[ii, jj]
        horizontal = np.hypot(np.diff(xs), np.diff(ys))
        if np.any(np.abs(np.diff(z)) > surface["maxGrade"] * horizontal + 0.01):
            raise ValueError(f"slope mismatch along lane: {index}")
        results.append(
            {
                "id": f"embankment-{index}",
                "width_min_units": float(width.min()),
                "width_max_units": float(width.max()),
                "min_static_clearance_units": float(clearance[ii, jj].min()),
                "length_units": float(np.hypot(horizontal, np.diff(z)).sum()),
                "direction": "unverified",
                "points": np.round(np.column_stack((xs, ys, z)), 4).tolist(),
            }
        )
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, type=Path)
    parser.add_argument("--orthomap", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    surface = json.loads(args.surface.read_bytes())
    digest = hashlib.sha256(args.orthomap.read_bytes()).hexdigest()
    if surface["areaId"] != "nizhny-kremlin" or digest != surface["sources"]["orthomapSha256"]:
        raise ValueError("orthomap and inspected road tile differ")
    with Image.open(args.orthomap) as image:
        gray = np.asarray(image.convert("L"), dtype=np.float64)
    separators = paint_evidence(gray, surface["grid"])
    lanes = lane_centers(separators, surface)
    report = {
        "schema": "sphere.lane-preview.v1",
        "worldId": surface["worldId"],
        "areaId": surface["areaId"],
        "mapRevision": surface["mapRevision"],
        "orthomapSha256": digest,
        "separators": separators,
        "lanes": lanes,
    }
    args.output.write_text(json.dumps(report, separators=(",", ":")) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "separators": [
                    {k: v for k, v in item.items() if k != "ends"} for item in separators
                ],
                "lanes": [{k: v for k, v in item.items() if k != "points"} for item in lanes],
            }
        )
    )


if __name__ == "__main__":
    main()
