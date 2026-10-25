"""Conservative reconstruction checks; finite exports alone are not a scene."""
from __future__ import annotations

import math


def sparse_condition(camera_centers, points):
    """Detect points collapsed onto camera centers, invariant to SfM scale/origin.

    Low reprojection errors are meaningless for zero-length observation rays.
    The 1e-5 path-span epsilon is a numerical degeneracy test, not metres.
    """
    import numpy as np

    cameras, xyz = np.asarray(camera_centers, dtype=float), np.asarray(points, dtype=float)
    if (cameras.ndim != 2 or cameras.shape[1] != 3 or not 2 <= len(cameras) <= 240
            or xyz.ndim != 2 or xyz.shape[1] != 3 or not 1 <= len(xyz) <= 2000000
            or not np.isfinite(cameras).all() or not np.isfinite(xyz).all()):
        raise ValueError('sparse_geometry_invalid')
    span = float(np.linalg.norm(np.ptp(cameras, axis=0)))
    if not math.isfinite(span) or span <= 0:
        raise ValueError('sparse_camera_path_degenerate')
    near = 0
    for start in range(0, len(xyz), 2048):
        distance = np.linalg.norm(xyz[start:start + 2048, None, :] - cameras[None, :, :], axis=2)
        near += int((distance.min(axis=1) < span * 1e-5).sum())
    fraction = near / len(xyz)
    return dict(near_camera_points=near, near_camera_fraction=fraction,
                camera_span_units=span, passed=fraction <= .01)


def reference_quality(metrics):
    """Baseline appearance guard at recorded poses, not a held-out/navigation test.

    These explicit thresholds catch grossly blurred/broken outputs; passing does
    not certify unseen viewpoints, metric geometry or obstacle avoidance.
    """
    views = metrics.get('views', [])
    if (metrics.get('schema') != 'sphere-reference-render-evaluation-v1'
            or metrics.get('training') is not False or metrics.get('held_out') is not False
            or metrics.get('resolution_limit') != 960 or not 3 <= len(views) <= 9):
        raise ValueError('reference_metrics_invalid')
    values = []
    for view in views:
        psnr, ssim = view.get('psnr'), view.get('ssim')
        if (isinstance(psnr, bool) or isinstance(ssim, bool)
                or not isinstance(psnr, (int, float)) or not isinstance(ssim, (int, float))
                or not math.isfinite(psnr) or not math.isfinite(ssim)
                or not 0 <= psnr <= 100 or not -1 <= ssim <= 1):
            raise ValueError('reference_metrics_nonfinite_or_invalid')
        values.append((psnr, ssim))
    mean_psnr = sum(row[0] for row in values) / len(values)
    mean_ssim = sum(row[1] for row in values) / len(values)
    min_psnr, min_ssim = min(row[0] for row in values), min(row[1] for row in values)
    passed = mean_psnr >= 22 and mean_ssim >= .75 and min_psnr >= 18 and min_ssim >= .65
    return dict(state='passed' if passed else 'rejected', mean_psnr=mean_psnr, mean_ssim=mean_ssim,
                min_psnr=min_psnr, min_ssim=min_ssim, reference_views=len(values),
                held_out=False, resolution_limit=960,
                policy=dict(mean_psnr=22, mean_ssim=.75, min_psnr=18, min_ssim=.65),
                navigation_qualified=False)
