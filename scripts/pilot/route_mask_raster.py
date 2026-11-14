"""Versioned reconstruction masks derived from the runtime feature domain.

Each target pixel is allowed only if its complete normalized cell overlaps no
excluded canonical pixel. This deliberately avoids resampling a mask as a
photograph and makes non-integer scaling conservative at cell boundaries.
"""
from __future__ import annotations

POLICY = 'runtime_feature_mask_cells_conservative_v1'
SCHEMA = 'sphere-reconstruction-mask-raster-v1'
CANONICAL_SIZE = (960, 540)


def reconstruction_mask(exclusions, size):
    import cv2
    import numpy as np

    from motor_worker.landmarks import RouteViewProfile
    from motor_worker.route_localization import SIZE, feature_mask

    if (not isinstance(size, (tuple, list)) or len(size) != 2
            or any(type(v) is not int or not 1 <= v <= 4096 for v in size)
            or size[0] * size[1] > 8 * 1024 * 1024):
        raise ValueError('reconstruction_mask_geometry')
    if SIZE != CANONICAL_SIZE:
        raise ValueError('reconstruction_mask_runtime_size_changed')
    width, height = size
    if not exclusions:
        # Preserve reconstruction mode=none; the legacy navigation profile
        # independently inserts a watermark and is not equivalent in this mode.
        return np.full((height, width), 255, np.uint8)
    profile = RouteViewProfile('00000000-0000-4000-8000-000000000000', *CANONICAL_SIZE,
                               (0., 0., 1., 1.), tuple(exclusions))
    canonical = feature_mask(profile)
    if (width, height) == CANONICAL_SIZE:
        return canonical
    cw, ch = CANONICAL_SIZE
    x = np.arange(width, dtype=np.int64)
    y = np.arange(height, dtype=np.int64)
    x0, x1 = x*cw//width, ((x+1)*cw+width-1)//width
    y0, y1 = y*ch//height, ((y+1)*ch+height-1)//height
    integral = cv2.integral((canonical == 0).astype(np.uint8), sdepth=cv2.CV_32S)
    result = np.empty((height, width), np.uint8)
    # Keep temporary allocations bounded even for full-resolution captures.
    for start in range(0, height, 128):
        end = min(height, start + 128)
        low, high = y0[start:end, None], y1[start:end, None]
        covered = (integral[high, x1] - integral[low, x1]
                   - integral[high, x0] + integral[low, x0])
        result[start:end] = np.where(covered == 0, 255, 0)
    return result


def raster_provenance():
    return dict(schema=SCHEMA, policy=POLICY, canonical_size=list(CANONICAL_SIZE),
                canonical_mask='runtime_feature_mask_profile_exclusions',
                canonical_margin_pixels=8,
                resampling='exclude_if_target_cell_overlaps_any_excluded_canonical_cell',
                none_mode='unmasked_reconstruction_runtime_profile_may_add_watermark',
                consumers=['prepared_image_masks', 'route_video_tracks', 'motion_sampling'],
                feature_support='centers_only_sift_descriptors_and_lk_windows_not_bounded',
                motion_sampling='initial_and_destination_centers_masked',
                endpoint_resection='independent_mask_unverified',
                dynamic_foreground='not_detected')
