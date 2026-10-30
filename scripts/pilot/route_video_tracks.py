"""Build SfM observations from continuous real-video corner tracks.

Unlike descriptor matching, an observation keeps its identity through every
intervening video frame. Newly measured subpixel observations are not generated
images, interpolated poses, learned descriptors or metric ground truth.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_masks import excluded_rectangles
from scripts.pilot.camera_pixel_conventions import tracking_points_to_colmap
from scripts.pilot.video_observations import track_source_points


def shared_track_pairs(previous, current):
    """Feature indices correspond only when the video tracker preserved identity."""
    import numpy as np
    lookup={int(identity):index for index,identity in enumerate(current)}
    return np.asarray([(index,lookup[int(identity)]) for index,identity in enumerate(previous)
                       if int(identity) in lookup],dtype=np.uint32).reshape(-1,2)


def build_video_track_database(job, prepared, source_database, output, check, *, max_lag=8, progress=None):
    import cv2
    import numpy as np
    import pycolmap as p
    from motor_worker.browser_teach import decoded_browser,validate_browser

    job,prepared,source_database,output=map(Path,(job,prepared,source_database,output))
    if output.exists() or source_database.is_symlink() or not 1<=max_lag<=8:
        raise ValueError('video_tracks_exclusive_output')
    check();capture=validate_browser(job/'input')
    provenance=json.loads((prepared/'reconstruction-input.json').read_bytes())
    if provenance['source_manifest_sha256']!=hashlib.sha256((job/'input/manifest.json').read_bytes()).hexdigest():
        raise ValueError('video_tracks_source_binding')
    selected={row['source_index']:row for row in provenance['images']}
    if not 10<=len(selected)<=240:raise ValueError('video_tracks_view_quota')
    control=json.loads((job/'control.json').read_bytes());width,height=capture.geometry
    # Keep fine facades/road texture through turns. This is a bounded CPU
    # observation budget, independent of the ordinary stream's resolution.
    scale=min(1.,1280/max(width,height));size=(round(width*scale),round(height*scale));cv2.setNumThreads(2)
    mask=np.full((size[1],size[0]),255,dtype='uint8');mask[:int(size[1]*.2)]=0
    for x1,y1,x2,y2 in excluded_rectangles(control.get('mask','none')):
        mask[int(y1*size[1]):int(y2*size[1]),int(x1*size[0]):int(x2*size[0])]=0
    with sqlite3.connect(source_database.resolve().as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(output) as dst:src.backup(dst)
    with p.Database.open(output) as db:
        images={image.name:image for image in db.read_all_images()}
        if len(images)!=len(selected) or any(Path(row['image']).name not in images for row in selected.values()):
            raise ValueError('video_tracks_image_binding')
        db.clear_keypoints();db.clear_descriptors();db.clear_matches();db.clear_two_view_geometries()
    previous=None;points=np.empty((0,2),dtype='float32');ids=np.empty(0,dtype='int64');next_id=0
    history=[];pairs=[];began=checked=time.monotonic();decoded=0;counts=[];previous_tick=None;breaks=[]
    for row,frame in decoded_browser(capture):
        now=time.monotonic()
        if now-began>300:raise RuntimeError('video_tracks_timeout')
        if now-checked>3:
            check();checked=now
            if progress:progress(decoded,len(capture.frames))
        gray=cv2.resize(frame.to_ndarray(format='gray'),size,interpolation=cv2.INTER_AREA)
        if previous_tick is not None and row['relative_ticks_90k']-previous_tick>22500:
            # A matching endpoint is not evidence for unrecorded intermediate
            # frames. Restart measured identities instead of bridging a gap.
            breaks.append(dict(sourceIndex=row['index'],seconds=row['relative_ticks_90k']/90000,
                               gapSeconds=(row['relative_ticks_90k']-previous_tick)/90000))
            points=np.empty((0,2),dtype='float32');ids=np.empty(0,dtype='int64');history=[]
        if previous is not None and len(points):
            moved,good=track_source_points(previous,gray,points,tolerance=.75)
            points=moved[good];ids=ids[good]
            inside=(points[:,0]>=5)&(points[:,0]<size[0]-5)&(points[:,1]>=5)&(points[:,1]<size[1]-5)
            points=points[inside];ids=ids[inside]
            allowed=mask[np.rint(points[:,1]).astype(int),np.rint(points[:,0]).astype(int)]>0
            points=points[allowed];ids=ids[allowed]
        if row['index'] in selected:
            selection=selected[row['index']]
            if row['relative_ticks_90k']!=selection['relative_ticks_90k']:raise ValueError('video_tracks_time_binding')
            allowed=mask.copy()
            for x,y in points:cv2.circle(allowed,(round(float(x)),round(float(y))),7,0,-1)
            needed=2000-len(points)
            new=cv2.goodFeaturesToTrack(gray,needed,.007,8,mask=allowed) if needed>=30 else None
            if new is not None:
                new=new[:,0];points=np.concatenate([points,new]);ids=np.concatenate([ids,np.arange(next_id,next_id+len(new))]);next_id+=len(new)
            image=images[Path(selection['image']).name]
            keypoints=np.column_stack([tracking_points_to_colmap(points,(width,height),size),
                np.ones(len(points),dtype='float32'),np.zeros(len(points),dtype='float32')])
            with p.Database.open(output) as db:
                db.write_keypoints(image.image_id,keypoints.astype('float32'))
                for old_image,old_ids in history:
                    matches=shared_track_pairs(old_ids,ids)
                    if len(matches)>=15:
                        db.write_matches(old_image.image_id,image.image_id,matches)
                        pairs.append(dict(first=old_image.name,second=image.name,matches=len(matches)))
            history.append((image,ids.copy()));history=history[-max_lag:];counts.append(len(points))
        previous=gray;previous_tick=row['relative_ticks_90k'];decoded+=1
    if decoded!=len(capture.frames) or len(counts)!=len(selected):raise ValueError('video_tracks_incomplete')
    report=dict(schema='sphere-video-track-database-v1',decodedFrames=decoded,views=len(counts),
        observations=sum(counts),trackIdentities=next_id,pairs=pairs,seconds=time.monotonic()-began,
        trackingResolution=list(size),maxCorners=2000,forwardBackwardPixels=.75,descriptorsGenerated=False,
        pixelCoordinates='colmap_corner_centers_after_resize_v1',
        sourceGapLimitSeconds=.25,trackingBreaks=breaks,
        sourceModified=False,posesInterpolated=False,physicalActions=0)
    write_json(output.with_suffix('.tracks.json'),report)
    return report
