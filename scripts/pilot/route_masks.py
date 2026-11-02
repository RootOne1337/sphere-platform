"""Shared normalized static presets; not dynamic-object segmentation."""
MODES = ('none', 'avatar', 'game')
WATERMARK = (0., .975, 1., 1.)
VEHICLE_BODY = (.25, .72, .73, 1.)
VEHICLE_MIRROR = (.20, .55, .40, 1.)
VEHICLE_HUD = ((0., 0., 1., .25), (0., 0., .2, .33),
               (0., .48, .25, 1.), (.77, .37, 1., 1.))


def excluded_rectangles(mode):
    if mode not in MODES:
        raise ValueError('invalid_processing_options')
    if mode == 'none':
        return ()
    avatar = (.33, .45, .67, 1.)
    if mode == 'avatar':
        return (avatar, WATERMARK)
    return ((0., 0., 1., .25), (0., .56, .25, 1.), (.83, .52, 1., 1.), avatar, WATERMARK)


def capture_exclusions(mode, manifest):
    """Use the recorded control profile, never infer geometry from HUD pixels.

    A vehicle capture has mirrors/handlebars and a lower dashboard instead of
    the usual standing avatar. Its pedals and right-hand HUD extend to the
    left/above the old game preset. These static rectangles are only exclusions;
    they do not identify players, buildings, sky or drivable space.
    """
    base = excluded_rectangles(mode)  # Validate even when no preset is applied.
    profile = (manifest.get('config') or {}).get('profile') or {}
    if mode == 'none' or profile.get('mode') != 'vehicle_buttons':
        return base
    if profile.get('hudProfile') != 'black_russia_scooter_v1':
        # Pedal mode alone cannot identify a game's HUD layout. Keep only the
        # central foreground/footer exclusion until a calibrated preset exists.
        return excluded_rectangles('avatar')
    return (*VEHICLE_HUD, VEHICLE_BODY, VEHICLE_MIRROR, WATERMARK) if mode == 'game' else (VEHICLE_BODY, VEHICLE_MIRROR, WATERMARK)
