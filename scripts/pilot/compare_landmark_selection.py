"""Compare landmark budgeting on one saved SfM model; no navigation actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_landmark_builder import select_spatially_diverse


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run(model, geometry, output):
    sys.path.insert(0, str(Path(".local-pilot/reconstruction-tools/pycolmap-4.2.1").resolve()))
    import pycolmap

    if output.exists():
        raise ValueError("comparison_output_exists")
    files = [
        geometry,
        *(
            model / name
            for name in ("cameras.bin", "images.bin", "points3D.bin", "frames.bin", "rigs.bin")
            if (model / name).is_file()
        ),
    ]
    before = {str(path): digest(path) for path in files}
    source = json.loads(geometry.read_text("utf-8"))
    rec = pycolmap.Reconstruction(model)
    names = [camera["image"] for camera in source["cameras"]]
    lookup = {name: i for i, name in enumerate(names)}
    images = {image.name: image for image in rec.images.values()}
    if (
        len(lookup) != len(names)
        or any(name not in images for name in names)
        or rec.num_cameras() != 1
    ):
        raise ValueError("comparison_camera_binding")
    matrices = [images[name].cam_from_world().matrix() for name in names]
    camera = next(iter(rec.cameras.values()))
    K = np.diag([960 / camera.width, 540 / camera.height, 1.0]) @ camera.calibration_matrix()
    rows = []
    for point in rec.points3D.values():
        views = tuple(
            sorted(
                {
                    lookup[rec.images[element.image_id].name]
                    for element in point.track.elements
                    if rec.images[element.image_id].name in lookup
                }
            )
        )
        if views:
            rows.append((len(views), tuple(point.xyz), None, views))
    rows.sort(key=lambda row: -row[0])
    selected, evidence = select_spatially_diverse(rows, matrices, K, 4096)

    def summary(subset):
        bands, times = Counter(), Counter()
        for row in subset:
            view = row[3][len(row[3]) // 2]
            point = matrices[view][:, :3] @ np.asarray(row[1]) + matrices[view][:, 3]
            projected = K @ point
            if point[2] <= 1e-5 or not np.isfinite(projected).all():
                continue
            x, y = projected[:2] / projected[2]
            if 0 <= x < 960 and 0 <= y < 540:
                bands[int(y // 180)] += 1
                times[min(7, 8 * view // len(matrices))] += 1
        return dict(bands=[bands[i] for i in range(3)], time_bins=[times[i] for i in range(8)])

    if {str(path): digest(path) for path in files} != before:
        raise ValueError("comparison_source_changed")
    output.mkdir(parents=True)
    report = dict(
        schema="sphere-landmark-selection-comparison-v1",
        source_sha256=before,
        dataset="same_sfm_model_not_independent",
        candidates=len(rows),
        previous=summary(rows[:4096]),
        diverse=summary(selected),
        selection=evidence,
        physical_actions=0,
        execution_qualified=False,
        limitations="Representative per-track image location; no live localization or dynamic-object truth.",
    )
    write_json(output / "report.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.model, args.geometry, args.output)
    print(json.dumps({k: result[k] for k in ("candidates", "previous", "diverse", "selection")}))
