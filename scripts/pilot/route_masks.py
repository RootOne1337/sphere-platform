"""Versioned static capture masks, never dynamic-object segmentation.

Saved runtime profiles/cache arrays retain their own mask. These helpers select
a policy only when a NEW reconstruction or export computes its exclusions.
"""
import hashlib
import json
import math

MODES = ('none', 'avatar', 'game')
WATERMARK = (0., .975, 1., 1.)
# Kept byte-for-byte reproducible for historical feature caches and receipts.
VEHICLE_BODY = (.25, .72, .73, 1.)
VEHICLE_MIRROR = (.20, .55, .40, 1.)
VEHICLE_HUD = ((0., 0., 1., .25), (0., 0., .2, .33),
               (0., .48, .25, 1.), (.77, .37, 1., 1.))
LEGACY_SCOOTER_POLICY = 'black_russia_scooter_rect_v1'
PRECISE_SCOOTER_POLICY = 'black_russia_scooter_precise_rect_v2'
PLAN_SCHEMA = 'sphere-capture-mask-plan-v1'
MAX_EXCLUDED_RECTANGLES = 16  # Existing RouteViewProfile wire-format bound.
PRECISE_FOREGROUND = ((.07, .74, .31, 1.), (.64, .72, .84, 1.),
                      (.28, .90, .73, 1.))
HUD_BASIS = (1920, 1080)
HUD_PADDING_PIXELS = 6


def _pixel_box(x1, y1, x2, y2):
    width, height = HUD_BASIS
    padding = HUD_PADDING_PIXELS
    return (max(0, math.floor(x1)-padding)/width,
            max(0, math.floor(y1)-padding)/height,
            min(width, math.ceil(x2)+padding+1)/width,
            min(height, math.ceil(y2)+padding+1)/height)


def _radar_strips():
    """Outward bounds cover the measured ellipse, including each strip's arc."""
    cx, cy, rx, ry = 158, 160, 156, 153
    rectangles = []
    for index in range(3):
        low, high = cy-ry+index*2*ry/3, cy-ry+(index+1)*2*ry/3
        nearest = min(high, max(low, cy))
        half_width = rx*math.sqrt(max(0., 1-((nearest-cy)/ry)**2))
        rectangles.append(_pixel_box(cx-half_width, low, cx+half_width, high))
    return tuple(rectangles)


def _precise_hud():
    # Measured fixed controls; grouping adjacent controls keeps the existing
    # sixteen-rectangle runtime format, without blanking entire image bands.
    boxes = (
        (51, 537, 173, 663),       # Microphone.
        (137, 730, 437, 1030),    # Joystick, including its active thumb range.
        (1574, 417, 1916, 513),   # Three neighbouring right-hand action icons.
        (1728, 529, 1886, 687),   # Motorcycle.
        (1728, 695, 1886, 853),   # Tyre.
        (1495, 869, 1887, 1037),  # Both pedals.
        (1350, 0, 1920, 121),     # Top controls.
        (1710, 126, 1900, 190),   # Balance display.
        (620, 865, 1290, 1040),   # Dashboard/speed cluster.
    )
    return (*_radar_strips(), *(_pixel_box(*box) for box in boxes))


def excluded_rectangles(mode):
    if mode not in MODES:
        raise ValueError('invalid_processing_options')
    if mode == 'none':
        return ()
    avatar = (.33, .45, .67, 1.)
    if mode == 'avatar':
        return (avatar, WATERMARK)
    return ((0., 0., 1., .25), (0., .56, .25, 1.), (.83, .52, 1., 1.), avatar, WATERMARK)


def capture_mask_plan(mode, manifest, *, policy_id=None):
    """Return an inspectable deterministic plan for this new computation.

    Explicit legacy selection reproduces old masks; it does not relabel cached
    observations as the new policy. Conservative foreground ROIs are separate
    from HUD controls and do not prove coverage under arbitrary camera turns.
    """
    base = excluded_rectangles(mode)  # Validate even when no preset is applied.
    if not isinstance(manifest, dict):
        raise ValueError('invalid_capture_mask_manifest')
    profile = (manifest.get('config') or {}).get('profile') or {}
    known = (profile.get('mode') == 'vehicle_buttons' and
             profile.get('hudProfile') == 'black_russia_scooter_v1')
    if policy_id not in {None, LEGACY_SCOOTER_POLICY, PRECISE_SCOOTER_POLICY}:
        raise ValueError('invalid_capture_mask_policy')
    if policy_id is not None and not known:
        raise ValueError('capture_mask_policy_capture_mismatch')
    hud, foreground, footer = (), (), ()
    selected = policy_id or (PRECISE_SCOOTER_POLICY if known else 'generic_rect_v1')
    if mode != 'none' and known:
        foreground = ((VEHICLE_BODY, VEHICLE_MIRROR) if selected == LEGACY_SCOOTER_POLICY
                      else PRECISE_FOREGROUND)
        footer = (WATERMARK,)
        if mode == 'game':
            hud = VEHICLE_HUD if selected == LEGACY_SCOOTER_POLICY else _precise_hud()
        rectangles = (*hud, *foreground, *footer)
    elif mode == 'none':
        rectangles = ()
    else:
        # Unknown games never inherit the Black Russia HUD calibration.
        rectangles = (excluded_rectangles('avatar') if profile.get('mode') == 'vehicle_buttons'
                      else base)
    if len(rectangles) > MAX_EXCLUDED_RECTANGLES:
        raise ValueError('capture_mask_rectangle_quota')
    plan = dict(schema=PLAN_SCHEMA, policy_id=selected, mode=mode,
                coordinate_system='normalized_xyxy',
                geometry_basis=list(HUD_BASIS) if known else None,
                static_hud_rectangles=[list(rect) for rect in hud],
                foreground_rectangles=[list(rect) for rect in foreground],
                footer_rectangles=[list(rect) for rect in footer],
                excluded_rectangles=[list(rect) for rect in rectangles],
                hud_padding_source_pixels=HUD_PADDING_PIXELS if known and
                    selected == PRECISE_SCOOTER_POLICY and mode == 'game' else 0,
                runtime_feature_margin_pixels=8,
                rasterization='consumer_integer_bounds_not_a_stored_mask_rewrite',
                dynamic_foreground_coverage='unknown',
                coverage_limits=['fixed_screen_control_layout',
                    'foreground_rois_are_conservative_not_semantic_labels',
                    'arbitrary_camera_yaw_pitch_and_other_layouts_unvalidated'],
                execution_qualified=False)
    canonical = json.dumps(plan, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    plan['sha256'] = hashlib.sha256(canonical).hexdigest()
    return plan


def capture_exclusions(mode, manifest, *, policy_id=None):
    """Existing normalized-rectangle API; sealed old runtime masks stay stored."""
    return tuple(tuple(rect) for rect in capture_mask_plan(mode, manifest,
                                                        policy_id=policy_id)['excluded_rectangles'])
