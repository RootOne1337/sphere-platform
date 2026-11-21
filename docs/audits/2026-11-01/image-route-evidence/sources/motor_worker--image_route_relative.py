"""Two-view camera-relative diagnostic; no navigation or actuation authority.

Pixels are OpenCV pixel-center coordinates; intrinsics must use the same pixels.
The caller binds both images and timestamps. Estimated translation has no scale.
"""
from __future__ import annotations

import math

SCHEMA = 'sphere-image-relative-goal-v1'
MAX_MATCHES = 4096


def estimate_relative_goal(query_pixels, target_pixels, intrinsics, *, width, height):
    """Estimate target-camera direction in query-camera coordinates, or unknown."""
    result = dict(schema=SCHEMA, status='unknown', reason='invalid_input',
                  Rtarget_from_query=None, goal_direction_query_camera=None,
                  yaw_radians=None, pitch_radians=None, support=None,
                  metric_scale_known=False, position_known=False, arrival_confirmed=False,
                  execution_qualified=False, camera_vehicle_alignment_known=False)
    try:
        import cv2 as cv
        import numpy as np
        if type(width) is not int or type(height) is not int or (width, height) != (960, 540):
            return result
        a = np.asarray(query_pixels, dtype=np.float64)
        b = np.asarray(target_pixels, dtype=np.float64)
        K = np.asarray(intrinsics, dtype=np.float64)
        if (a.ndim != 2 or a.shape[1:] != (2,) or b.shape != a.shape
                or len(a) > MAX_MATCHES or K.shape != (3, 3)
                or not np.isfinite(a).all() or not np.isfinite(b).all() or not np.isfinite(K).all()
                or not np.allclose(K[2], [0, 0, 1], atol=1e-9)
                or abs(K[1, 0]) > 1e-9 or abs(K[0, 1]) > 1e-9
                or K[0, 0] <= 0 or K[1, 1] <= 0
                or not 0 <= K[0, 2] < width or not 0 <= K[1, 2] < height
                or (a < 0).any() or (b < 0).any()
                or (a[:, 0] >= width).any() or (b[:, 0] >= width).any()
                or (a[:, 1] >= height).any() or (b[:, 1] >= height).any()
                or len(np.unique(a, axis=0)) != len(a) or len(np.unique(b, axis=0)) != len(b)):
            return result
        if len(a) < 24:
            result['reason'] = 'insufficient_correspondences'
            return result

        def grid(points):
            cells = np.floor(points / [width, height] * 4).astype(int)
            return dict(occupied=int(len(np.unique(cells[:, 1]*4+cells[:, 0]))),
                        rows=int(len(np.unique(cells[:, 1]))), cols=int(len(np.unique(cells[:, 0]))))

        def supported(mask):
            n = int(mask.sum())
            ga, gb = grid(a[mask]), grid(b[mask])
            ok = n >= 20 and n / len(a) >= .5 and all(
                g['occupied'] >= 4 and g['rows'] >= 2 and g['cols'] >= 2 for g in (ga, gb))
            return ok, ga, gb

        def is_rotation(R):
            return (R.shape == (3, 3) and np.isfinite(R).all()
                    and np.allclose(R.T @ R, np.eye(3), atol=1e-4)
                    and abs(float(np.linalg.det(R))-1) < 1e-4)

        def rotation_only():
            H, mask = cv.findHomography(a, b, cv.RANSAC, 2.)
            if H is None or mask is None or not np.isfinite(H).all():
                return None
            mask = np.asarray(mask).reshape(-1).astype(bool)
            if mask.size != len(a): return None
            ok, ga, gb = supported(mask)
            if not ok: return None
            M = np.linalg.inv(K) @ H @ K
            if np.linalg.det(M) < 0: M = -M
            u, singular, vh = np.linalg.svd(M)
            if singular[-1] <= 0 or singular[0]/singular[-1] > 1.03: return None
            R = u @ vh
            if not is_rotation(R): return None
            ah = np.column_stack((a[mask], np.ones(int(mask.sum()))))
            ph = (K @ R @ np.linalg.inv(K) @ ah.T).T
            if not np.isfinite(ph).all() or (np.abs(ph[:, 2]) < 1e-9).any(): return None
            error = np.linalg.norm(ph[:, :2]/ph[:, 2, None]-b[mask], axis=1)
            if float(np.median(error)) > 2: return None
            return R, dict(correspondences=len(a), pose_inliers=int(mask.sum()),
                           inlier_fraction=float(mask.mean()), query_grid=ga, target_grid=gb,
                           homography_singular_ratio=float(singular[0]/singular[-1]),
                           rotation_transfer_median_px=float(np.median(error)),
                           rotation_transfer_p95_px=float(np.percentile(error,95)))

        # Pure rotation can also produce a convincing but fictitious essential
        # solution. Prefer the verified rotation-only explanation when it fits.
        fallback = rotation_only()
        if fallback is not None:
            R, summary = fallback
            result.update(status='orientation_only', reason='rotation_homography_no_translation',
                          Rtarget_from_query=R.tolist(), support=summary)
            return result
        E, initial_mask = cv.findEssentialMat(a, b, K, method=cv.RANSAC, prob=.999, threshold=1.5)
        candidates = []
        if E is not None and initial_mask is not None:
            E = np.asarray(E, dtype=float)
            if E.ndim == 2 and E.shape[1] == 3 and E.shape[0] % 3 == 0:
                matrices = [E[i:i+3] for i in range(0, E.shape[0], 3)]
            elif E.ndim == 2 and E.shape[0] == 3 and E.shape[1] % 3 == 0:
                matrices = [E[:, i:i+3] for i in range(0, E.shape[1], 3)]
            else:
                matrices = []
            for matrix in matrices:
                if not np.isfinite(matrix).all(): continue
                try:
                    _, R, t, pmask = cv.recoverPose(matrix, a, b, K, mask=np.asarray(initial_mask, dtype=np.uint8).copy())
                except cv.error:
                    continue
                mask = np.asarray(pmask).reshape(-1).astype(bool)
                if mask.size != len(a) or not is_rotation(R): continue
                ok, ga, gb = supported(mask)
                if not ok: continue
                ray_a = np.linalg.solve(K, np.column_stack((a[mask], np.ones(int(mask.sum())))).T).T
                ray_b = np.linalg.solve(K, np.column_stack((b[mask], np.ones(int(mask.sum())))).T).T @ R
                ray_a /= np.linalg.norm(ray_a, axis=1)[:, None]
                ray_b /= np.linalg.norm(ray_b, axis=1)[:, None]
                angles = np.degrees(np.arccos(np.clip(np.sum(ray_a*ray_b,axis=1),-1,1)))
                F = np.linalg.inv(K).T @ matrix @ np.linalg.inv(K)
                ah = np.column_stack((a[mask], np.ones(int(mask.sum()))));bh = np.column_stack((b[mask], np.ones(int(mask.sum()))))
                Fa = ah @ F.T; Ftb = bh @ F
                error = np.abs(np.sum(bh*Fa, axis=1))/np.sqrt(np.maximum(Fa[:,0]**2+Fa[:,1]**2+Ftb[:,0]**2+Ftb[:,1]**2, 1e-20))
                direction = -R.T @ np.asarray(t).reshape(3)
                norm = float(np.linalg.norm(direction))
                if not np.isfinite(angles).all() or not np.isfinite(error).all() or not math.isfinite(norm) or norm < 1e-9: continue
                summary = dict(correspondences=len(a), pose_inliers=int(mask.sum()), inlier_fraction=float(mask.mean()),
                               query_grid=ga, target_grid=gb, median_parallax_deg=float(np.median(angles)),
                               sampson_median_px=float(np.median(error)), sampson_p95_px=float(np.percentile(error,95)))
                candidates.append((int(mask.sum()), -float(np.median(error)), R, direction/norm, summary))
        if candidates:
            _, _, R, direction, summary = max(candidates, key=lambda row:(row[0],row[1]))
            if summary['median_parallax_deg'] >= .3:
                result.update(status='goal_direction', reason='two_view_direction_unscaled',
                              Rtarget_from_query=R.tolist(), goal_direction_query_camera=direction.tolist(),
                              yaw_radians=float(math.atan2(direction[0],direction[2])),
                              pitch_radians=float(math.atan2(direction[1],math.hypot(direction[0],direction[2]))), support=summary)
                return result
        result['reason'] = 'insufficient_parallax_or_geometry'
        return result
    except (ValueError, TypeError, OverflowError, ArithmeticError, ImportError):
        return result
    except Exception as error:
        # OpenCV failures are unknown, not evidence of a pose. Unexpected errors
        # are allowed through so defects are not silently converted to success.
        if 'cv' in locals() and isinstance(error, cv.error):
            result['reason'] = 'geometry_solver_failed'
            return result
        if 'np' in locals() and isinstance(error, np.linalg.LinAlgError):
            result['reason'] = 'geometry_solver_failed'
            return result
        raise
