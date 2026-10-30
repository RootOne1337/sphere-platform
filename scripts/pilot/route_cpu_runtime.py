"""Initialize the small live CPU runtime without a huge default BLAS pool.

Restore the environment immediately: child reconstruction tools retain their
own settings. OpenCV tracking keeps four explicit native threads. NumPy's BLAS
pool is initialized once at one thread for the small matrices used by live PnP.
"""
from __future__ import annotations

import os
import sys

_profile = None


def initialize_route_cpu_runtime(*, load=None):
    global _profile
    if load is None and _profile is not None:
        return dict(_profile)
    previous = os.environ.get('OPENBLAS_NUM_THREADS')
    preloaded = 'numpy' in sys.modules
    os.environ['OPENBLAS_NUM_THREADS'] = '1'
    try:
        if load is not None:
            load()
        else:
            import numpy  # Initialize its native pool while the override is in scope.
            import cv2
            cv2.setNumThreads(4)
    finally:
        if previous is None:
            os.environ.pop('OPENBLAS_NUM_THREADS', None)
        else:
            os.environ['OPENBLAS_NUM_THREADS'] = previous
    profile = dict(numpyAlreadyLoaded=preloaded,requestedBlasThreads=1,opencvThreads=4,
                   childEnvironmentRestored=True)
    if load is None:
        _profile = profile
    return dict(profile)
