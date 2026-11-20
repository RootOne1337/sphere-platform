"""Estimate the native camera focal length from non-planar map points and held-out pixels."""

import math

import cv2
import numpy as np

CALIBRATION_FLAGS = (
    cv2.CALIB_USE_INTRINSIC_GUESS
    | cv2.CALIB_FIX_ASPECT_RATIO
    | cv2.CALIB_FIX_PRINCIPAL_POINT
    | cv2.CALIB_ZERO_TANGENT_DIST
    | cv2.CALIB_FIX_K1
    | cv2.CALIB_FIX_K2
    | cv2.CALIB_FIX_K3
)


def seed_pose(points, pixels, width, height):
    def camera(f):
        return np.array([[f, 0, width / 2], [0, f, height / 2], [0, 0, 1.0]], float)

    # RANSAC is only the seed. Both focal estimates below are independently fitted.
    best = None
    for hfov in range(55, 146, 10):
        k = camera(width / (2 * math.tan(math.radians(hfov) / 2)))
        ok, _, _, ids = cv2.solvePnPRansac(
            points,
            pixels,
            k,
            None,
            iterationsCount=200,
            reprojectionError=4.0,
            confidence=0.99,
            flags=cv2.SOLVEPNP_AP3P,
        )
        if ok and ids is not None and (best is None or len(ids) > len(best[1])):
            best = k, ids.ravel()
    return best


def focal_from_map(points, pixels, width, height):
    """Return a horizontal angle only when separate image regions predict each other's pixels."""
    if len(points) < 45:
        return None
    cells = (np.floor(pixels[:, 0] / 76) + np.floor(pixels[:, 1] / 60)).astype(int) % 2
    best = seed_pose(points, pixels, width, height)
    if best is None or len(best[1]) < 42:
        return None
    k, idx = best
    views = []
    for side in (0, 1):
        take = idx[cells[idx] == side]
        hold = idx[cells[idx] != side]
        if (
            min(len(take), len(hold)) < 16
            or cv2.contourArea(cv2.convexHull(pixels[take])) < 0.08 * width * height
        ):
            return None
        spread = np.linalg.svd(points[take] - points[take].mean(0), compute_uv=False)
        if spread[-1] < max(0.12, 0.018 * spread[0]):
            return None
        try:
            _, result, _, rv, tv = cv2.calibrateCamera(
                [points[take]],
                [pixels[take]],
                (width, height),
                k.copy(),
                np.zeros(5),
                flags=CALIBRATION_FLAGS,
            )
        except cv2.error:
            return None
        repro = cv2.projectPoints(points[hold], rv[0], tv[0], result, None)[0][:, 0]
        err = np.linalg.norm(repro - pixels[hold], axis=1)
        angle = math.degrees(2 * math.atan2(width / 2, result[0, 0]))
        if (
            not 40 <= angle <= 150
            or np.median(err) > 1.75
            or np.percentile(err, 80) > 3.5
            or np.min((points[hold] @ cv2.Rodrigues(rv[0])[0].T + tv[0].ravel())[:, 2]) <= 0
        ):
            return None
        views.append(angle)
    return sum(views) / 2 if abs(views[0] - views[1]) < 1.8 else None


def stationary_focal(points, pixels, width, height):
    """Reserve an extra quarter of the image cells to qualify one stationary image."""
    if len(points) < 120:
        return None
    group = (np.floor(pixels[:, 0] / 42) + np.floor(pixels[:, 1] / 38)).astype(int) % 4
    train = group != 0
    hold = ~train
    if hold.sum() < 24:
        return None
    seed = seed_pose(points[train], pixels[train], width, height)
    if seed is None or len(seed[1]) < 50:
        return None
    initial, ids = seed
    xyz_train = points[train][ids]
    uv_train = pixels[train][ids]
    if np.linalg.svd(xyz_train - xyz_train.mean(0), compute_uv=False)[-1] < 0.25:
        return None
    try:
        k = initial.copy()
        for threshold in (2.6, 1.8, 1.4):
            _, k, _, rv, tv = cv2.calibrateCamera(
                [xyz_train], [uv_train], (width, height), k, np.zeros(5), flags=CALIBRATION_FLAGS
            )
            err = np.linalg.norm(
                cv2.projectPoints(xyz_train, rv[0], tv[0], k, None)[0][:, 0] - uv_train, axis=1
            )
            good = err < threshold
            if good.sum() < 40:
                return None
            xyz_train, uv_train = xyz_train[good], uv_train[good]
    except cv2.error:
        return None
    r, t = rv[0], tv[0]
    angle = math.degrees(2 * math.atan2(width / 2, k[0, 0]))
    if not 40 <= angle <= 150:
        return None
    xyz = points[hold]
    uv = pixels[hold]
    prediction = cv2.projectPoints(xyz, r, t, k, None)[0][:, 0]
    good = (np.linalg.norm(uv - prediction, axis=1) < 2.2) & (
        (xyz @ cv2.Rodrigues(r)[0].T + t.ravel())[:, 2] > 0.5
    )
    if (
        good.sum() < 20
        or good.mean() < 0.50
        or cv2.contourArea(cv2.convexHull(uv[good])) < 0.07 * width * height
    ):
        return None
    return angle
