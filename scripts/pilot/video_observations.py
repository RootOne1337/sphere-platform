"""Observed forward/backward video tracks; lost points never gain predictions."""
from __future__ import annotations


def track_source_points(previous,current,points,*,tolerance):
    import cv2 as cv
    import numpy as np
    old=np.asarray(points,dtype=np.float32).reshape(-1,1,2)
    failed=np.zeros(len(old),dtype=bool)
    if not len(old):
        return old[:,0].copy(),failed
    moved,status,_=cv.calcOpticalFlowPyrLK(previous,current,old,None,winSize=(21,21),maxLevel=3)
    if moved is None or status is None or moved.shape!=old.shape or status.size!=len(old):
        return old[:,0].copy(),failed
    finite=np.isfinite(moved).all(axis=(1,2))
    # OpenCV must not receive NaN/Inf points even if the failed LK status is 0.
    safe=moved.copy();safe[~finite]=old[~finite]
    back,reverse,_=cv.calcOpticalFlowPyrLK(current,previous,safe,None,winSize=(21,21),maxLevel=3)
    if back is None or reverse is None or back.shape!=old.shape or reverse.size!=len(old):
        return old[:,0].copy(),failed
    good=(status.reshape(-1).astype(bool)&reverse.reshape(-1).astype(bool)&finite
          &np.isfinite(back).all(axis=(1,2))
          &(np.linalg.norm(back-old,axis=2).reshape(-1)<=tolerance))
    return safe[:,0],good
