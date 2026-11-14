"""Explicit pixel-center transforms across OpenCV resizing and COLMAP.

COLMAP uses pixel corners (the first pixel center is .5,.5). OpenCV uses
integer pixel centers. Resize acts on pixel cells, before changing the origin.
"""
from __future__ import annotations


def _geometry(size):
    import numpy as np
    if (not isinstance(size,(tuple,list)) or len(size)!=2
            or any(type(value) is not int or not 1<=value<=16384 for value in size)):
        raise ValueError('pixel_transform_geometry')
    return np.asarray(size,dtype=np.float64)


def tracking_points_to_colmap(points, source_size, tracking_size):
    """Measured OpenCV centers -> original-image COLMAP corner coordinates."""
    import numpy as np
    xy=np.asarray(points,dtype=np.float64)
    if xy.ndim!=2 or xy.shape[1]!=2 or not np.isfinite(xy).all():
        raise ValueError('pixel_transform_points')
    return (xy+.5)*(_geometry(source_size)/_geometry(tracking_size))


def colmap_calibration_to_opencv(calibration, source_size, target_size):
    """Preserve rays while scaling COLMAP K to OpenCV target pixel centers."""
    import numpy as np
    matrix=np.asarray(calibration,dtype=np.float64)
    if (matrix.shape!=(3,3) or not np.isfinite(matrix).all()
            or matrix[0,0]<=0 or matrix[1,1]<=0
            or not np.allclose(matrix[2],[0,0,1],rtol=0,atol=1e-12)):
        raise ValueError('pixel_transform_calibration')
    scale=_geometry(target_size)/_geometry(source_size)
    result=np.diag([*scale,1.])@matrix
    result[:2,2]-=.5
    return result
