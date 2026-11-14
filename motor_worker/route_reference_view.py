"""Bind recorded camera orientation to an unchanged sparse map, without media time hints."""
import hashlib
import json
from pathlib import Path


def reference_rotations(path, route, sha256):
    import numpy as np
    path=Path(path)
    if path.is_symlink() or not 0<path.stat().st_size<=16*1024**2:
        raise ValueError('route_reference_geometry_quota')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=sha256:
        raise ValueError('route_reference_geometry_changed')
    data=json.loads(raw)
    cameras=data.get('cameras')
    if not isinstance(cameras,list) or not cameras:
        return None  # Legacy maps keep the explicitly horizontal mode.
    if len(cameras)>256 or data.get('source_manifest_sha256')!=route.source_capture_sha256:
        return None
    indexed={c.get('ticks_90k'):c for c in cameras}
    if len(indexed)!=len(cameras):return None
    rotations=[]
    for seconds,center in zip(route.source_seconds,route.camera_trace):
        camera=indexed.get(round(seconds*90000))
        if camera is None:return None
        matrix=np.asarray(camera.get('camera_to_world'),dtype=float)
        if (matrix.shape!=(3,4) or not np.isfinite(matrix).all()
                or not np.allclose(matrix[:,3],center,rtol=1e-6,atol=1e-6)
                or not np.allclose(matrix[:,:3].T@matrix[:,:3],np.eye(3),atol=1e-5)
                or not np.isclose(np.linalg.det(matrix[:,:3]),1,atol=1e-5)):
            return None
        rotations.append(matrix[:,:3].T.copy())
    return tuple(rotations)
