"""Offline epipolar correspondence experiment, not a steering estimator.

A fundamental matrix can fit 3D scene correspondences without requiring one
image plane; it does not establish vehicle pose, obstacle clearance, scale,
or truth of the matches, particularly in a dynamic scene.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EpipolarDisplacement:
    state: str
    x_pixels: float | None
    inliers: int
    cells: int
    reason: str


def compare_epipolar(reference, query):
    import cv2 as cv
    import numpy as np

    for image in (reference, query):
        if (
            not isinstance(image, np.ndarray)
            or image.dtype != np.uint8
            or image.shape != (540, 960, 3)
        ):
            raise ValueError("expected_960x540_bgr_uint8")
    detector = cv.ORB_create(nfeatures=2000, fastThreshold=9)
    mask = np.zeros((540, 960), np.uint8)
    mask[45:420, 15:945] = 255
    ref_k, ref_d = detector.detectAndCompute(cv.cvtColor(reference, cv.COLOR_BGR2GRAY), mask)
    query_k, query_d = detector.detectAndCompute(cv.cvtColor(query, cv.COLOR_BGR2GRAY), mask)
    if ref_d is None or query_d is None or len(ref_d) < 20 or len(query_d) < 20:
        return EpipolarDisplacement("unknown", None, 0, 0, "insufficient_features")
    pairs = cv.BFMatcher(cv.NORM_HAMMING).knnMatch(query_d, ref_d, k=2)
    good = [
        a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < 0.75 * b.distance
    ]
    good = list(
        {m.trainIdx: m for m in sorted(good, key=lambda m: m.distance, reverse=True)}.values()
    )
    if len(good) < 20:
        return EpipolarDisplacement("unknown", None, 0, 0, "insufficient_matches")
    q = np.float32([query_k[m.queryIdx].pt for m in good])
    r = np.float32([ref_k[m.trainIdx].pt for m in good])
    matrix, mask_f = cv.findFundamentalMat(q, r, cv.FM_RANSAC, 1.5, 0.995)
    if matrix is None or matrix.shape != (3, 3) or mask_f is None or not np.isfinite(matrix).all():
        return EpipolarDisplacement("unknown", None, 0, 0, "fundamental_matrix_failed")
    accepted = mask_f.ravel().astype(bool)
    count = int(accepted.sum())
    cells = min(len({(int(x // 240), int(y // 180)) for x, y in pts[accepted]}) for pts in (q, r))
    if count < 20 or count / len(good) < 0.4 or cells < 4:
        return EpipolarDisplacement("unknown", None, count, cells, "geometry_not_supported")
    return EpipolarDisplacement(
        "measured",
        float(np.median(r[accepted, 0] - q[accepted, 0])),
        count,
        cells,
        "epipolar_correspondence_not_pose",
    )
