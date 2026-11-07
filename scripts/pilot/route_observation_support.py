"""Bounded in-sample 3D track support; diagnostic only, never a route gate."""
from __future__ import annotations

MAX_IMAGES = 240
MAX_POINTS = 2_000_000
MAX_OBSERVATIONS = 2_000_000
WORST_FRAME_LIMIT = 12


def compact_observation_support(report):
    """Bound the embedded product report; complete camera rows stay offline-only."""
    if report.get('status') != 'complete':
        return dict(report)
    rows = report['cameras']
    worst = sorted(rows, key=lambda r: (r['reprojection_le_4px'], r['ticks_90k'], r['image']))
    return {key: value for key, value in report.items() if key != 'cameras'} | {
        'frame_count': len(rows), 'worst_frames': worst[:WORST_FRAME_LIMIT],
        'worst_frames_truncated': len(rows) > WORST_FRAME_LIMIT}


class _CheckFailure(Exception):
    def __init__(self, error):
        self.error = error


def observation_support(rec, cameras, *, check=None):
    """Count reciprocal >=3-distinct-registered-view tracks observed per image.

    Reports invalid on incomplete, inconsistent or oversized reconstruction data.
    Only the same image's observed 3D points are projected; no cloud projection.
    """
    try:
        if check is not None and not callable(check):
            raise ValueError('check_not_callable')
        def guarded_check():
            if check is not None:
                try:
                    check()
                except Exception as error:
                    raise _CheckFailure(error) from error
        return _measure(rec, cameras, guarded_check)
    except _CheckFailure as error:
        raise error.error
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, RuntimeError,
            OverflowError, ArithmeticError, ImportError, MemoryError) as exc:
        return {'status': 'invalid', 'reason': str(exc)[:120] or type(exc).__name__,
                'execution_qualified': False, 'admission_effect': 'none'}


def _measure(rec, cameras, check):
    check()
    import numpy as np

    if not isinstance(cameras, list) or len(cameras) > MAX_IMAGES:
        raise ValueError('camera_limit_or_binding')
    reg_ids = list(rec.reg_image_ids())
    if not reg_ids or len(reg_ids) > MAX_IMAGES or len(set(reg_ids)) != len(reg_ids):
        raise ValueError('registered_image_limit')
    if len(rec.points3D) > MAX_POINTS:
        raise ValueError('point_limit')
    binding = {}
    for c in cameras:
        if (not isinstance(c, dict) or not isinstance(c.get('image'), str)
                or not 1 <= len(c['image'].encode('utf-8')) <= 64
                or c['image'] in binding or type(c.get('ticks_90k')) is not int):
            raise ValueError('camera_binding_invalid')
        binding[c['image']] = c['ticks_90k']
    images = {int(i): rec.image(i) for i in reg_ids}
    if len(binding) != len(images) or {im.name for im in images.values()} != set(binding):
        raise ValueError('camera_binding_mismatch')
    per_image = {i: [] for i in images}
    track_counts = {}; total = 0
    checked_points = checked_elements = 0
    for pid, point in rec.points3D.items():
        checked_points += 1
        if checked_points % 1024 == 0:
            check()
        xyz = np.asarray(point.xyz, dtype=float)
        if xyz.shape != (3,) or not np.isfinite(xyz).all():
            raise ValueError('nonfinite_point')
        count = point.track.length()
        total += count
        if total > MAX_OBSERVATIONS:
            raise ValueError('track_observation_limit')
        if count >= 1024:
            check()
        elements = point.track.elements
        if len(elements) != count:
            raise ValueError('track_length_invalid')
        seen = set(); grouped = {}
        for elem in elements:
            checked_elements += 1
            if checked_elements % 1024 == 0:
                check()
            image_id, idx = int(elem.image_id), int(elem.point2D_idx)
            key = (image_id, idx)
            if image_id not in images or idx < 0 or key in seen:
                raise ValueError('track_element_invalid')
            seen.add(key)
            feature = images[image_id].point2D(idx)
            if not feature.has_point3D() or int(feature.point3D_id) != int(pid):
                raise ValueError('track_reciprocity_invalid')
            # A 3D point contributes at most once per image even if a track
            # contains multiple feature indices from that image.
            if image_id not in grouped or idx < grouped[image_id][0]:
                grouped[image_id] = (idx, feature.xy)
        track_counts[int(pid)] = len(seen)
        if len(grouped) >= 3:
            for image_id, (_, xy) in grouped.items():
                per_image[image_id].append((xyz, xy))
    # Check the reverse direction without building a global pair matrix.
    image_counts = {}; examined = 0
    for im in images.values():
        check()
        count = int(im.num_points2D())
        if count < 0:
            raise ValueError('image_observation_limit')
        examined += count
        if examined > MAX_OBSERVATIONS:
            raise ValueError('image_observation_limit')
        points2d = im.points2D
        if len(points2d) != count:
            raise ValueError('image_observation_count_invalid')
        for feature in points2d:
            checked_elements += 1
            if checked_elements % 1024 == 0:
                check()
            if feature.has_point3D():
                pid = int(feature.point3D_id)
                if pid not in track_counts:
                    raise ValueError('image_reciprocity_invalid')
                image_counts[pid] = image_counts.get(pid, 0) + 1
    if any(image_counts.get(pid, 0) != count for pid, count in track_counts.items()):
        raise ValueError('image_reciprocity_invalid')
    rows = []
    for image_id, im in images.items():
        check()
        camera = im.camera; width, height = int(camera.width), int(camera.height)
        if width <= 0 or height <= 0:
            raise ValueError('camera_dimensions_invalid')
        pairs = per_image[image_id]; raw = len(pairs)
        positive_count = supported_count = occupied = 0
        if raw:
            xyz = np.asarray([v[0] for v in pairs], dtype=float)
            obs = np.asarray([v[1] for v in pairs], dtype=float)
            if obs.shape != (raw, 2) or not np.isfinite(obs).all():
                raise ValueError('image_observation_nonfinite')
            pose = im.cam_from_world()
            camera_xyz = xyz @ np.asarray(pose.rotation.matrix()).T + np.asarray(pose.translation)
            positive = np.isfinite(camera_xyz).all(axis=1) & (camera_xyz[:, 2] > 0)
            inside = (obs[:, 0] >= 0) & (obs[:, 0] < width) & (obs[:, 1] >= 0) & (obs[:, 1] < height)
            valid = positive & inside
            positive_count = int(valid.sum())
            if positive_count:
                projected = np.asarray(camera.img_from_cam(camera_xyz[valid]), dtype=float)
                if projected.shape != (positive_count, 2):
                    raise ValueError('projection_shape_invalid')
                residual = np.linalg.norm(projected - obs[valid], axis=1)
                supported = np.isfinite(projected).all(axis=1) & np.isfinite(residual) & (residual <= 4.)
                accepted = obs[valid][supported]; supported_count = int(supported.sum())
                if supported_count:
                    cells = np.floor(accepted / [width, height] * 4).astype(int)
                    occupied = int(np.unique(cells[:, 1] * 4 + cells[:, 0]).size)
        rows.append(dict(image=im.name, ticks_90k=binding[im.name],
                         raw_eligible_tracks=raw, positive_depth_inside=positive_count,
                         reprojection_le_4px=supported_count, occupied_grid_4x4=occupied))
    rows.sort(key=lambda row: (row['ticks_90k'], row['image']))
    values = sorted(row['reprojection_le_4px'] for row in rows)
    return dict(status='complete', schema='sphere-observation-support-v1', cameras=rows,
                summary=dict(min=values[0], median=float(np.median(values)),
                             p10=float(np.percentile(values, 10)),
                             count_under_6=sum(v < 6 for v in values),
                             count_under_15=sum(v < 15 for v in values)),
                summary_measure='reprojection_le_4px', track_observations=total,
                execution_qualified=False, admission_effect='none',
                caveat='In-sample diagnostic; counts do not certify camera pose or navigation.')
