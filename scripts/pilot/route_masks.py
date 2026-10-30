"""Shared normalized static presets; not dynamic-object segmentation."""
MODES = ('none', 'avatar', 'game')
WATERMARK = (0., .975, 1., 1.)


def excluded_rectangles(mode):
    if mode not in MODES:
        raise ValueError('invalid_processing_options')
    if mode == 'none':
        return ()
    avatar = (.33, .45, .67, 1.)
    if mode == 'avatar':
        return (avatar, WATERMARK)
    return ((0., 0., 1., .25), (0., .56, .25, 1.), (.83, .52, 1., 1.), avatar, WATERMARK)
