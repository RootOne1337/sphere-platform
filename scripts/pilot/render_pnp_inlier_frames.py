"""Render a bounded offline proof sheet of measured PnP inlier locations.

Original RGB is checked against recorded per-frame hashes. Pixels are a visual
diagnostic, not semantic labels, a route, or a navigation authorization.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from motor_worker.browser_teach import decoded_browser, validate_browser
from scripts.pilot.reconstruct_route import checkpoint


def render(capture, probe_report, inlier_report, output, *, indices):
    import cv2 as cv
    import numpy as np

    capture, probe_report, inlier_report, output = map(
        Path, (capture, probe_report, inlier_report, output)
    )
    checkpoint(output.parent)
    if output.exists():
        raise FileExistsError(output)
    if (
        type(indices) is not tuple
        or not 1 <= len(indices) <= 4
        or len(set(indices)) != len(indices)
    ):
        raise ValueError("inlier_visual_selection_invalid")
    probe = json.loads(probe_report.read_text(encoding="utf-8"))
    measurements = json.loads(inlier_report.read_text(encoding="utf-8"))
    if (
        probe.get("execution_qualified") is not False
        or measurements.get("execution_qualified") is not False
    ):
        raise ValueError("inlier_visual_scope_invalid")
    query = {s["source_index"]: s for s in probe["samples"]}
    measured = {s["source_index"]: s for s in measurements["samples"]}
    if (
        len(query) != len(probe["samples"])
        or len(measured) != len(measurements["samples"])
        or any(i not in query or i not in measured for i in indices)
    ):
        raise ValueError("inlier_visual_frames_missing")
    capture = validate_browser(capture)
    if (
        hashlib.sha256(capture.originals["manifest.json"]).hexdigest()
        != probe["capture_manifest_sha256"]
    ):
        raise ValueError("inlier_visual_capture_mismatch")
    frames = {}
    for row, decoded in decoded_browser(capture):
        if row["index"] not in indices:
            continue
        rgb = decoded.to_ndarray(format="rgb24")
        sample = query[row["index"]]
        points = measured[row["index"]]
        if (
            hashlib.sha256(rgb.tobytes()).hexdigest() != sample["source_rgb_sha256"]
            or points["state"] != "verified_again"
        ):
            raise ValueError("inlier_visual_frame_binding")
        rgb = cv.resize(rgb, (960, 540), interpolation=cv.INTER_AREA)
        bgr = cv.cvtColor(rgb, cv.COLOR_RGB2BGR)
        coords = np.asarray(points["accepted_xy"], dtype=float)
        if (
            coords.shape != (points["inliers"], 2)
            or not np.isfinite(coords).all()
            or (coords < 0).any()
            or (coords[:, 0] >= 960).any()
            or (coords[:, 1] >= 540).any()
        ):
            raise ValueError("inlier_visual_points_invalid")
        shade = bgr.copy()
        for x, y in coords:
            cv.circle(shade, (int(round(x)), int(round(y))), 2, (80, 240, 255), -1, cv.LINE_AA)
        bgr = cv.addWeighted(shade, 0.80, bgr, 0.20, 0)
        cv.line(bgr, (0, 360), (959, 360), (255, 225, 100), 1, cv.LINE_AA)
        cv.rectangle(bgr, (0, 0), (960, 39), (12, 20, 30), -1)
        cv.putText(
            bgr,
            f"{sample['seconds']:.2f}s | inliers {len(coords)} | cyan line: bottom third",
            (10, 27),
            cv.FONT_HERSHEY_SIMPLEX,
            0.63,
            (238, 244, 250),
            1,
            cv.LINE_AA,
        )
        frames[row["index"]] = bgr
        if len(frames) == len(indices):
            break
    if len(frames) != len(indices):
        raise ValueError("inlier_visual_frame_decode")
    sheet = np.vstack([frames[i] for i in indices])
    if not cv.imwrite(str(output), sheet):
        raise OSError("inlier_visual_write_failed")
    return {"frames": len(indices), "physical_actions": 0, "execution_qualified": False}
