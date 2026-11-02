"""Offline spatial diagnosis of saved camera geometry versus KLT tracks.

Regions overlap and are image-space, not semantic classes. All images are from
one recording. This produces neither metric geometry nor control authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_epipolar_diagnostic import epipolar_residuals
from scripts.pilot.route_workspace import resource_checkpoint

REGIONS = {
    "upper": (12, 948, 45, 270),
    "lower": (12, 948, 270, 520),
    "left": (12, 480, 45, 520),
    "right": (480, 948, 45, 520),
}


def run(prepared, models, output, *, start=27.5, end=33.0):
    import cv2 as cv
    import numpy as np
    import pycolmap

    cv.setNumThreads(4)
    cv.setRNGSeed(17)
    prepared, output = Path(prepared), Path(output)
    resource_checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    provenance = prepared / "reconstruction-input.json"
    source = json.loads(provenance.read_text(encoding="utf-8"))
    rows = {Path(r["image"]).name: r for r in source["images"]}
    paths = [provenance]
    recs = {}
    for name, path in models.items():
        path = Path(path)
        if path.is_symlink():
            raise ValueError("region_model_symlink")
        paths.extend(sorted(path.glob("*.bin")))
        rec = pycolmap.Reconstruction(path)
        recs[name] = (rec, {im.name: im for im in rec.images.values() if im.has_pose})
    if not recs:
        raise ValueError("region_models_missing")

    def digest(path):
        with path.open("rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()

    before = {str(p): digest(p) for p in paths}
    common = set.intersection(*(set(images) for rec, images in recs.values()))
    names = sorted(
        (n for n in common if n in rows and start <= rows[n]["relative_ticks_90k"] / 90000 <= end),
        key=lambda n: rows[n]["relative_ticks_90k"],
    )
    if len(names) < 3:
        raise ValueError("region_insufficient_views")

    def load(name):
        path = prepared / "images" / name
        if path.is_symlink() or digest(path) != rows[name]["png_sha256"]:
            raise ValueError("region_image_integrity")
        image = cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
        if image is None:
            raise ValueError("region_image_decode")
        return cv.resize(image, (960, 540), interpolation=cv.INTER_AREA)

    output.mkdir()
    write_json(
        output / "intent.json", {"scope": "offline_spatial_klt_diagnostic", "physical_actions": 0}
    )
    previous = load(names[0])
    results = []
    for index in range(1, len(names)):
        if index % 4 == 0:
            resource_checkpoint(output)
        current = load(names[index])
        mask = np.zeros((540, 960), np.uint8)
        mask[45:520, 12:948] = 255
        a = cv.goodFeaturesToTrack(
            previous, maxCorners=2000, qualityLevel=0.01, minDistance=5, mask=mask, blockSize=5
        )
        entry = {
            "first": names[index - 1],
            "second": names[index],
            "seconds": rows[names[index]]["relative_ticks_90k"] / 90000,
            "regions": {},
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
                    good &= (b[:, 0] >= 0) & (b[:, 0] < 960) & (b[:, 1] >= 0) & (b[:, 1] < 540)
                    a, b = a[good].astype(float), b[good].astype(float)
                    for region, (x0, x1, y0, y1) in REGIONS.items():
                        selected = (
                            (a[:, 0] >= x0) & (a[:, 0] < x1) & (a[:, 1] >= y0) & (a[:, 1] < y1)
                        )
                        aa, bb = a[selected], b[selected]
                        d = {"tracks": len(aa), "ransac_inlier_fraction": None, "models": {}}
                        if len(aa) >= 24:
                            F, inliers = cv.findFundamentalMat(aa, bb, cv.FM_RANSAC, 1.5, 0.999)
                            valid = (
                                None
                                if F is None or F.shape != (3, 3) or inliers is None
                                else inliers.ravel().astype(bool)
                            )
                            if valid is not None:
                                d["ransac_inlier_fraction"] = float(valid.mean())
                            for name, (rec, images) in recs.items():
                                first, second = images[names[index - 1]], images[names[index]]
                                c1, c2 = rec.cameras[first.camera_id], rec.cameras[second.camera_id]
                                k1 = (
                                    np.diag([960 / c1.width, 540 / c1.height, 1.0])
                                    @ c1.calibration_matrix()
                                )
                                k2 = (
                                    np.diag([960 / c2.width, 540 / c2.height, 1.0])
                                    @ c2.calibration_matrix()
                                )
                                errors = epipolar_residuals(
                                    k1,
                                    k2,
                                    first.cam_from_world().matrix(),
                                    second.cam_from_world().matrix(),
                                    aa,
                                    bb,
                                )
                                d["models"][name] = (
                                    None if errors is None else float(np.median(errors))
                                )
                        entry["regions"][region] = d
        previous = current
        results.append(entry)
    if {str(p): digest(p) for p in paths} != before:
        raise ValueError("region_model_changed")
    report = {
        "schema": "sphere-klt-spatial-audit-v1",
        "samples": results,
        "regions": REGIONS,
        "same_recording": True,
        "overlapping_image_regions": True,
        "semantic_static_mask": False,
        "ground_truth": False,
        "metric_scale": None,
        "physical_actions": 0,
        "execution_qualified": False,
        "source_sha256": before,
    }
    write_json(output / "report.json", report)
    return report
