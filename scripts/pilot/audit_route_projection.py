"""Offline camera-trace projection audit; never a ground-route/input permit.

Consumes already estimated held-out poses. It does not localize, train, infer
depth, replay recorded input or contact a device. Output must be a new folder.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(geometry_path, heldout_path, images, output):
    import cv2 as cv
    import numpy as np

    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    heldout = json.loads(heldout_path.read_text(encoding="utf-8"))
    if (geometry.get("schema") != "sphere-recovered-scene-v1"
            or heldout.get("schema") != "sphere-route011321-heldout-pose-probe-v1"
            or geometry["source_manifest_sha256"] != heldout["source_manifest_sha256"]
            or heldout["images_not_used_for_map_or_gaussian_training"] is not True):
        raise ValueError("incompatible_evidence")
    cameras = sorted(geometry["cameras"], key=lambda row: row["ticks_90k"])
    trace = np.asarray([row["center"] for row in cameras], dtype=np.float64)
    directions = np.diff(trace, axis=0)
    lengths = np.linalg.norm(directions, axis=1)
    if len(trace) < 2 or not np.isfinite(trace).all() or (lengths <= 0).any():
        raise ValueError("invalid_camera_trace")
    intrinsics = cameras[0]["intrinsics"]
    if any(row["intrinsics"] != intrinsics for row in cameras):
        raise ValueError("variable_intrinsics_not_supported_by_this_probe")
    width, height = intrinsics["width"], intrinsics["height"]
    K = np.array([[intrinsics["fx"], 0, intrinsics["cx"]],
                  [0, intrinsics["fy"], intrinsics["cy"]], [0, 0, 1]])
    inputs = {str(geometry_path): digest(geometry_path), str(heldout_path): digest(heldout_path)}
    rows, comparisons = [], []
    output.mkdir(parents=True, exist_ok=False)
    for row in heldout["views"]:
        index = row["source_index"]
        image_path = images / f"{index:08d}.png"
        expected = row["png_sha256"]
        if digest(image_path) != expected:
            raise ValueError("heldout_rgb_hash_changed")
        inputs[str(image_path)] = expected
        image = cv.imread(str(image_path))
        if image is None or image.shape[:2] != (height, width):
            raise ValueError("heldout_dimensions_changed")
        record = dict(source_index=index, source_rgb_sha256=expected,
                      pose_accepted=row["global_retrieval"]["accepted"],
                      ground_route=False, occlusion_checked=False)
        polyline = []
        state = "POSE UNKNOWN - NO LINE"
        if record["pose_accepted"]:
            pose = np.asarray(heldout["poses"][str(index)], dtype=np.float64)
            if pose.shape != (3, 4) or not np.isfinite(pose).all():
                raise ValueError("invalid_heldout_pose")
            R, t = pose[:, :3], pose[:, 3]
            center = -R.T @ t
            fractions = np.clip(np.sum((center - trace[:-1]) * directions, axis=1) / lengths**2, 0, 1)
            nearest = trace[:-1] + fractions[:, None] * directions
            distances = np.linalg.norm(nearest - center, axis=1)
            order = np.argsort(distances)
            at = int(order[0])
            ambiguous = any(abs(int(other) - at) > 2
                            and distances[other] <= distances[at] + lengths.mean() * .15
                            for other in order[1:])
            record.update(segment=at, cross_track_units=float(distances[at]),
                          progress_ambiguous=bool(ambiguous))
            if ambiguous:
                state = "ROUTE PROGRESS AMBIGUOUS - NO LINE"
            else:
                for world in trace[at + 1:at + 9]:
                    local = R @ world + t
                    if local[2] <= 1e-4:
                        if polyline:
                            break
                        continue
                    pixel = K @ local
                    pixel = pixel[:2] / pixel[2]
                    # Numerical check of coordinate conventions, not ground truth.
                    oracle = cv.projectPoints(world[None], cv.Rodrigues(R)[0], t, K, None)[0][0, 0]
                    comparisons.append(float(np.linalg.norm(pixel - oracle)))
                    if not (0 <= pixel[0] < width and 0 <= pixel[1] < height):
                        if polyline:
                            break
                        continue
                    polyline.append(pixel.tolist())
                state = "CAMERA TRACE ONLY - NOT GROUND OR SAFE PATH"
        record.update(polyline_px=polyline, visible_points=len(polyline), state=state)
        scale = 960 / width
        preview = cv.resize(image, (960, round(height * scale)), interpolation=cv.INTER_AREA)
        if len(polyline) >= 2:
            points = np.rint(np.asarray(polyline) * scale).astype(np.int32)
            cv.polylines(preview, [points], False, (0, 0, 0), 7)
            cv.polylines(preview, [points], False, (255, 40, 240), 3)
        cv.rectangle(preview, (0, 0), (960, 54), (16, 16, 16), -1)
        cv.putText(preview, f"Held-out {index} | {row['seconds']:.3f}s", (12, 21),
                   cv.FONT_HERSHEY_SIMPLEX, .55, (240, 240, 240), 1, cv.LINE_AA)
        cv.putText(preview, state, (12, 44), cv.FONT_HERSHEY_SIMPLEX, .47,
                   (140, 210, 255), 1, cv.LINE_AA)
        if not cv.imwrite(str(output / f"{index:08d}-projection.png"), preview):
            raise OSError("projection_image_write_failed")
        rows.append(record)
    changed = [name for name, sha in inputs.items() if digest(Path(name)) != sha]
    if changed:
        raise ValueError("source_changed_during_probe")
    report = dict(schema="sphere-offline-camera-trace-projection-audit-v1", rows=rows,
                  source_manifest_sha256=geometry["source_manifest_sha256"],
                  source_hashes=inputs, source_unchanged=True, same_capture=True, new_session=False,
                  progress_selection="nearest geometric camera-trace segment, ambiguous crossings rejected",
                  training=False, depth_inferred=False, physical_actions=0,
                  ground_route=False, metric_scale_known=False, navigation_qualified=False,
                  max_projection_formula_difference_px=max(comparisons, default=0),
                  projected_views=sum(len(row["polyline_px"]) >= 2 for row in rows),
                  pose_accepted=sum(row["pose_accepted"] for row in rows),
                  script_sha256=digest(Path(__file__).resolve()))
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("projected_views", "pose_accepted", "max_projection_formula_difference_px",
                       "source_unchanged", "navigation_qualified")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, required=True)
    parser.add_argument("--heldout-report", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.geometry, args.heldout_report, args.images, args.output)


if __name__ == "__main__":
    main()
