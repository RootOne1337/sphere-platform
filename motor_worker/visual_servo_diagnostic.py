"""Offline image-displacement diagnostic. No vehicle pose or control output.

Only a conservative, image-space statistic is returned. A shift may arise from
rotation, translation, forward motion, animation, or an incorrect match. It is
not an estimate of metres, road clearance, steering direction, or a drive permit.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Displacement:
    state: str
    x_pixels: float | None
    inliers: int
    cells: int
    reason: str
    center_x_pixels: float | None = None


def compare(reference, query):
    """Compare two 960x540 BGR images and return reference-minus-query x shift."""
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
        return Displacement("unknown", None, 0, 0, "insufficient_features")
    pairs = cv.BFMatcher(cv.NORM_HAMMING).knnMatch(query_d, ref_d, k=2)
    good = [
        a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < 0.75 * b.distance
    ]
    good = list(
        {m.trainIdx: m for m in sorted(good, key=lambda m: m.distance, reverse=True)}.values()
    )
    if len(good) < 20:
        return Displacement("unknown", None, 0, 0, "insufficient_matches")
    q = np.float32([query_k[m.queryIdx].pt for m in good])
    r = np.float32([ref_k[m.trainIdx].pt for m in good])
    matrix, inlier_mask = cv.findHomography(q, r, cv.RANSAC, 3.0)
    if matrix is None or inlier_mask is None or not np.isfinite(matrix).all():
        return Displacement("unknown", None, 0, 0, "homography_failed")
    accepted = inlier_mask.ravel().astype(bool)
    count = int(accepted.sum())
    cells = min(len({(int(x // 240), int(y // 180)) for x, y in pts[accepted]}) for pts in (q, r))
    corners = np.float32([[[0, 0], [960, 0], [960, 540], [0, 540]]])
    transformed = cv.perspectiveTransform(corners, matrix)[0]
    sane = (
        np.isfinite(transformed).all()
        and cv.isContourConvex(transformed)
        and 0.4 <= cv.contourArea(transformed, oriented=True) / (960 * 540) <= 2.5
    )
    if count < 15 or count / len(good) < 0.4 or cells < 4 or not sane:
        return Displacement("unknown", None, count, cells, "geometry_not_supported")
    center = cv.perspectiveTransform(np.float32([[[480, 270]]]), matrix)[0, 0]
    if not np.isfinite(center).all():
        return Displacement("unknown", None, count, cells, "center_projection_invalid")
    return Displacement(
        "measured",
        float(np.median(r[accepted, 0] - q[accepted, 0])),
        count,
        cells,
        "image_shift_only_not_pose",
        float(center[0] - 480),
    )
