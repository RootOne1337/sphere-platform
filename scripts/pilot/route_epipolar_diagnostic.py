"""Independent image-track consistency check, not a navigation or metric gate.

Extrinsics are world-to-camera, intrinsics/points use the same pixel geometry.
No correspondences are synthesized and no camera poses are modified.
"""
from __future__ import annotations


def epipolar_residuals(first_K, second_K, first_ext, second_ext, first_points, second_points):
    """Return Sampson pixel residuals, or None if translation is unobservable."""
    import numpy as np

    k1, k2, e1, e2, a, b = (np.asarray(x, dtype=np.float64) for x in
                            (first_K, second_K, first_ext, second_ext, first_points, second_points))
    if (k1.shape != (3, 3) or k2.shape != (3, 3) or e1.shape != (3, 4) or e2.shape != (3, 4)
            or a.ndim != 2 or a.shape[1] != 2 or b.shape != a.shape or not 8 <= len(a) <= 100000
            or not all(np.isfinite(x).all() for x in (k1, k2, e1, e2, a, b))):
        raise ValueError('epipolar_input_invalid')
    for k in (k1, k2):
        if k[0, 0] <= 0 or k[1, 1] <= 0 or abs(np.linalg.det(k)) <= 1e-12:
            raise ValueError('epipolar_calibration_invalid')
    for rotation in (e1[:, :3], e2[:, :3]):
        if (not np.allclose(rotation @ rotation.T, np.eye(3), rtol=1e-5, atol=1e-5)
                or not np.isclose(np.linalg.det(rotation), 1., rtol=1e-5, atol=1e-5)):
            raise ValueError('epipolar_rotation_invalid')
    rotation = e2[:, :3] @ e1[:, :3].T
    translation = e2[:, 3] - rotation @ e1[:, 3]
    length = np.linalg.norm(translation)
    if not np.isfinite(length) or length <= 1e-12:
        return None
    x, y, z = translation / length
    cross = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]], dtype=np.float64)
    fundamental = np.linalg.inv(k2).T @ cross @ rotation @ np.linalg.inv(k1)
    magnitude = np.linalg.norm(fundamental)
    if not np.isfinite(magnitude) or magnitude <= 1e-15:
        return None
    fundamental /= magnitude
    ah, bh = np.column_stack((a, np.ones(len(a)))), np.column_stack((b, np.ones(len(b))))
    fa, fb = ah @ fundamental.T, bh @ fundamental
    denom = np.sqrt(np.sum(fa[:, :2] ** 2, axis=1) + np.sum(fb[:, :2] ** 2, axis=1))
    valid = np.isfinite(denom) & (denom > 1e-12)
    if int(valid.sum()) < 8:
        return None
    values = np.abs(np.sum(bh[valid] * fa[valid], axis=1)) / denom[valid]
    if not np.isfinite(values).all():
        return None
    return values
