"""Bounded camera-rotation seeds for offline LK comparisons."""

from __future__ import annotations

import cv2 as cv
import numpy as np


def camera_rotation_homography(calibration, yaw_deg, pitch_deg):
    """Map reference rays into the query image under camera rotation alone."""
    yaw, pitch = np.deg2rad([yaw_deg, pitch_deg])
    yaw_rotation = cv.Rodrigues(np.array([0., yaw, 0.]))[0]
    pitch_rotation = cv.Rodrigues(np.array([pitch, 0., 0.]))[0]
    return calibration @ pitch_rotation @ yaw_rotation @ np.linalg.inv(calibration)


def choose_rotation_seed(reference, query, mask, calibration):
    """Rank 25 small rotations by masked gradient similarity at 160×90."""
    width, height = 160, 90
    size = (width, height)
    sx, sy = width / query.shape[1], height / query.shape[0]
    to_small = np.array([[sx, 0., (sx - 1.) / 2], [0., sy, (sy - 1.) / 2], [0., 0., 1.]])
    small_calibration = to_small @ calibration
    visible = cv.resize(mask, size, interpolation=cv.INTER_AREA) == 255
    # Ignore edges created by the HUD mask when gradients are resampled.
    visible = cv.erode(visible.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)

    def gradients(gray):
        small = cv.resize(gray, size, interpolation=cv.INTER_AREA)
        return cv.magnitude(cv.Sobel(small, cv.CV_32F, 1, 0), cv.Sobel(small, cv.CV_32F, 0, 1))

    reference_edges, query_edges = gradients(reference), gradients(query)
    reference_edges[~visible] = 0.
    visibility = visible.astype(np.uint8)
    min_overlap = max(1, .7 * np.count_nonzero(visible))
    best = None
    angles = (0, -4, 4, -8, 8)
    for yaw in angles:
        for pitch in angles:
            transform = camera_rotation_homography(small_calibration, yaw, pitch)
            warped_visibility = cv.warpPerspective(visibility, transform, size,
                                                   flags=cv.INTER_NEAREST).astype(bool)
            overlap = visible & warped_visibility
            if overlap.sum() < min_overlap:
                continue
            warped = cv.warpPerspective(reference_edges, transform, size)
            a, b = warped[overlap], query_edges[overlap]
            a, b = a - a.mean(), b - b.mean()
            denominator = np.linalg.norm(a) * np.linalg.norm(b)
            if denominator <= 1e-6:
                continue
            score = float(np.dot(a, b) / denominator)
            if best is None or score > best[0]:
                best = (score, yaw, pitch)
    if best is None:
        return None
    score, yaw, pitch = best
    return camera_rotation_homography(calibration, yaw, pitch), score, yaw, pitch
