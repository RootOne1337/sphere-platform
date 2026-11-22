"""Compare saved camera models against independently tracked image features.

All models and KLT observations come from one recording. The image tracks are
not SfM training correspondences, but this is not independent ground truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_epipolar_diagnostic import epipolar_residuals
from scripts.pilot.route_workspace import resource_checkpoint


def summarize(results, model_names):
    import numpy as np

    summary = {}
    for name in model_names:
        values = [
            r["models"][name]["median_px"]
            for r in results
            if name in r["models"] and r["models"][name]["median_px"] is not None
        ]
        inliers = [
            r["models"][name]["median_ransac_inliers_px"]
            for r in results
            if name in r["models"] and r["models"][name]["median_ransac_inliers_px"] is not None
        ]
        summary[name] = {
            "pairs": len(values),
            "median_of_pair_medians_px": None if not values else float(np.median(values)),
            "p90_pair_median_px": None if not values else float(np.percentile(values, 90)),
            "ransac_pairs": len(inliers),
            "ransac_inliers_median_of_pair_medians_px": None
            if not inliers
            else float(np.median(inliers)),
            "ransac_inliers_p90_pair_median_px": None
            if not inliers
            else float(np.percentile(inliers, 90)),
        }
    return summary


def run(prepared, models, output, *, start=25.0):
    import cv2 as cv
    import numpy as np
    import pycolmap

    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    prepared, output = Path(prepared), Path(output)
    resource_checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    if not models or len(set(models)) != len(models):
        raise ValueError("klt_models_invalid")
    provenance = prepared / "reconstruction-input.json"
    data = json.loads(provenance.read_text(encoding="utf-8"))
    rows = {Path(r["image"]).name: r for r in data["images"]}
    paths = [provenance]
    recs = {}
    for name, path in models.items():
        path = Path(path)
        if path.is_symlink():
            raise ValueError("klt_model_symlink")
        paths.extend(sorted(path.glob("*.bin")))
        rec = pycolmap.Reconstruction(path)
        recs[name] = (rec, {im.name: im for im in rec.images.values() if im.has_pose})

    def digest(path):
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    before = {str(p): digest(p) for p in paths}
    common = set.intersection(*(set(v[1]) for v in recs.values()))
    names = sorted(
        (n for n in common if n in rows and rows[n]["relative_ticks_90k"] / 90000 >= start),
        key=lambda n: rows[n]["relative_ticks_90k"],
    )
    if len(names) < 3:
        raise ValueError("klt_insufficient_common_views")

    def load(name):
        path = prepared / "images" / name
        if path.is_symlink() or digest(path) != rows[name]["png_sha256"]:
            raise ValueError("klt_source_image_changed")
        image = cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("klt_image_decode")
        return cv.resize(image, (960, 540), interpolation=cv.INTER_AREA)

    output.mkdir()
    write_json(
        output / "intent.json",
        {"scope": "offline_saved_models_and_original_images", "physical_actions": 0},
    )
    results = []
    previous = load(names[0])
    for i in range(1, len(names)):
        if i % 4 == 0:
            resource_checkpoint(output)
        current = load(names[i])
        mask = np.zeros((540, 960), np.uint8)
        mask[162:520, 12:948] = 255
        a = cv.goodFeaturesToTrack(
            previous, maxCorners=1200, qualityLevel=0.01, minDistance=6, mask=mask, blockSize=5
        )
        result = {
            "first": names[i - 1],
            "second": names[i],
            "seconds": rows[names[i]]["relative_ticks_90k"] / 90000,
            "tracks": 0,
            "ransac_inlier_fraction": None,
            "models": {},
        }
        if a is not None:
            kw = dict(
                winSize=(21, 21),
                maxLevel=3,
                criteria=(cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, 0.01),
            )
            b, status, _ = cv.calcOpticalFlowPyrLK(previous, current, a, None, **kw)
            if b is not None and status is not None:
                back, backstatus, _ = cv.calcOpticalFlowPyrLK(current, previous, b, None, **kw)
                if back is not None and backstatus is not None:
                    a = a.reshape(-1, 2)
                    b = b.reshape(-1, 2)
                    good = (
                        (status.ravel() == 1)
                        & (backstatus.ravel() == 1)
                        & (np.linalg.norm(back.reshape(-1, 2) - a, axis=1) <= 1)
                    )
                    good &= (b[:, 0] >= 0) & (b[:, 0] < 960) & (b[:, 1] >= 162) & (b[:, 1] < 520)
                    a, b = a[good].astype(float), b[good].astype(float)
                    result["tracks"] = len(a)
                    if len(a) >= 24:
                        matrix, inliers = cv.findFundamentalMat(a, b, cv.FM_RANSAC, 1.5, 0.999)
                        valid = (
                            None
                            if matrix is None or matrix.shape != (3, 3) or inliers is None
                            else inliers.ravel().astype(bool)
                        )
                        if valid is not None:
                            result["ransac_inlier_fraction"] = float(valid.mean())
                        for name, (rec, images) in recs.items():
                            x, y = images[names[i - 1]], images[names[i]]
                            k1 = (
                                np.diag(
                                    [
                                        960 / rec.cameras[x.camera_id].width,
                                        540 / rec.cameras[x.camera_id].height,
                                        1.0,
                                    ]
                                )
                                @ rec.cameras[x.camera_id].calibration_matrix()
                            )
                            k2 = (
                                np.diag(
                                    [
                                        960 / rec.cameras[y.camera_id].width,
                                        540 / rec.cameras[y.camera_id].height,
                                        1.0,
                                    ]
                                )
                                @ rec.cameras[y.camera_id].calibration_matrix()
                            )
                            residual = epipolar_residuals(
                                k1,
                                k2,
                                x.cam_from_world().matrix(),
                                y.cam_from_world().matrix(),
                                a,
                                b,
                            )
                            inlier_residual = (
                                None
                                if valid is None or int(valid.sum()) < 8
                                else epipolar_residuals(
                                    k1,
                                    k2,
                                    x.cam_from_world().matrix(),
                                    y.cam_from_world().matrix(),
                                    a[valid],
                                    b[valid],
                                )
                            )
                            result["models"][name] = {
                                "median_px": None
                                if residual is None
                                else float(np.median(residual)),
                                "median_ransac_inliers_px": None
                                if inlier_residual is None
                                else float(np.median(inlier_residual)),
                            }
        results.append(result)
        previous = current
    if {str(p): digest(p) for p in paths} != before:
        raise ValueError("klt_model_source_changed")
    summary = summarize(results, models)
    report = {
        "schema": "sphere-sfm-klt-comparison-v1",
        "samples": results,
        "summary": summary,
        "common_views": len(names),
        "same_recording": True,
        "dynamic_objects_filtered": False,
        "metric_scale": None,
        "ground_truth": False,
        "physical_actions": 0,
        "execution_qualified": False,
        "source_sha256": before,
    }
    write_json(output / "report.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prepared", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--model", action="append", required=True, help="name=COLMAP-directory")
    p.add_argument("--start", type=float, default=25.0)
    a = p.parse_args()
    models = {}
    for item in a.model:
        name, path = item.split("=", 1)
        if not name or name in models:
            raise ValueError("klt_models_invalid")
        models[name] = path
    result = run(a.prepared, models, a.output, start=a.start)
    print(json.dumps({"common_views": result["common_views"], "summary": result["summary"]}))


if __name__ == "__main__":
    main()
