"""Observed forward/backward video tracks; lost points never gain predictions."""
from __future__ import annotations


def track_source_points(previous,current,points,*,tolerance,window=21,levels=3):
    import cv2 as cv
    import numpy as np
    if type(window) is not int or window not in (21,31) or type(levels) is not int or levels not in (3,4):
        raise ValueError('video_track_pyramid_budget')
    old=np.asarray(points,dtype=np.float32).reshape(-1,1,2)
    failed=np.zeros(len(old),dtype=bool)
    if not len(old):
        return old[:,0].copy(),failed
    moved,status,_=cv.calcOpticalFlowPyrLK(previous,current,old,None,winSize=(window,window),maxLevel=levels)
    if moved is None or status is None or moved.shape!=old.shape or status.size!=len(old):
        return old[:,0].copy(),failed
    finite=np.isfinite(moved).all(axis=(1,2))
    # OpenCV must not receive NaN/Inf points even if the failed LK status is 0.
    safe=moved.copy();safe[~finite]=old[~finite]
    back,reverse,_=cv.calcOpticalFlowPyrLK(current,previous,safe,None,winSize=(window,window),maxLevel=levels)
    if back is None or reverse is None or back.shape!=old.shape or reverse.size!=len(old):
        return old[:,0].copy(),failed
    good=(status.reshape(-1).astype(bool)&reverse.reshape(-1).astype(bool)&finite
          &np.isfinite(back).all(axis=(1,2))
          &(np.linalg.norm(back-old,axis=2).reshape(-1)<=tolerance))
    return safe[:,0],good
