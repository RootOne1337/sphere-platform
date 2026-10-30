"""Select real source frames by measured image motion, keeping turns in view."""
from __future__ import annotations

import time

from scripts.pilot.route_masks import excluded_rectangles
from scripts.pilot.video_observations import track_source_points


def select_motion_rows(frames, motion, *, max_images=240):
    """Deterministic bounded selection; scores are pixels, never metres or poses."""
    if len(frames)<2 or not 2<=max_images<=240:
        raise ValueError('motion_sampling_budget')
    duration=frames[-1]['relative_ticks_90k']/90000
    threshold,minimum,maximum=20.,.12,max(.5,duration/200)
    for _ in range(20):
        selected,travel=[frames[0]],0.
        for row in frames[1:]:
            value=motion.get(row['index'],0.)
            if not isinstance(value,(int,float)) or not 0<=value<=1000:
                raise ValueError('motion_sampling_score')
            travel+=value
            elapsed=(row['relative_ticks_90k']-selected[-1]['relative_ticks_90k'])/90000
            if elapsed>=maximum or elapsed>=minimum and travel>=threshold:
                selected.append(row);travel=0.
        last=frames[-1]
        if selected[-1]['index']!=last['index']:
            if len(selected)>1 and last['relative_ticks_90k']-selected[-1]['relative_ticks_90k']<minimum*45000:
                selected[-1]=last
            else:selected.append(last)
        if len(selected)<=max_images:
            return frozenset(row['index'] for row in selected),dict(method='source-optical-motion-v1',
                views=len(selected),motionThresholdPixels=threshold,minSeconds=minimum,maxSeconds=maximum,
                metricScaleKnown=False,posesUsed=False,sourceFrames=len(frames))
        threshold*=1.25;minimum*=1.1;maximum*=1.1
    raise ValueError('motion_sampling_budget')


def sample_video(capture, mask_mode, check, progress=None):
    import cv2
    import numpy as np
    from motor_worker.browser_teach import decoded_browser

    width,height=capture.geometry;scale=min(1.,480/max(width,height));size=(round(width*scale),round(height*scale))
    mask=np.full((size[1],size[0]),255,dtype='uint8')
    for x1,y1,x2,y2 in excluded_rectangles(mask_mode):
        mask[int(y1*size[1]):int(y2*size[1]),int(x1*size[0]):int(x2*size[0])]=0
    previous=None;motion={};decoded=0;began=checked=time.monotonic();cv2.setNumThreads(2)
    for row,frame in decoded_browser(capture):
        now=time.monotonic()
        if now-began>180:raise RuntimeError('motion_sampling_timeout')
        if now-checked>3:
            check();checked=now
            if progress:progress(decoded,len(capture.frames))
        gray=cv2.resize(frame.to_ndarray(format='gray'),size,interpolation=cv2.INTER_AREA)
        if previous is not None:
            points=cv2.goodFeaturesToTrack(previous,180,.015,10,mask=mask)
            if points is not None and len(points)>=15:
                moved,good=track_source_points(previous,gray,points,tolerance=1.)
                if good.sum()>=15:motion[row['index']]=float(np.median(np.linalg.norm(moved-points[:,0],axis=1)[good]))
        previous=gray;decoded+=1
    if decoded!=len(capture.frames):raise ValueError('motion_sampling_decode')
    indices,report=select_motion_rows(capture.frames,motion)
    report.update(decodedFrames=decoded,seconds=time.monotonic()-began,trackingResolution=list(size),
                  scoresMeasured=len(motion),sourceModified=False)
    return indices,report
