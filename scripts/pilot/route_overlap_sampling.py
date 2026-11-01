"""Bounded offline real-frame overlap sampling; no poses or execution qualification."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from pathlib import Path


def plan_pose_gaps(frames, initial, bindings, motion, *, max_additions=24, max_selected=240):
    """Plan real-frame additions for flagged camera intervals; does not assess poses."""
    if (type(frames) is not list or len(frames) < 2 or type(initial) is not list
            or type(bindings) is not list or type(motion) is not dict
            or type(max_additions) is not int or not 0 <= max_additions <= 24
            or type(max_selected) is not int or not 2 <= max_selected <= 240):
        raise ValueError('pose_gap_invalid_input')
    if any(type(row) is not dict or type(row.get('index')) is not int
           or row['index'] != i or type(row.get('relative_ticks_90k')) is not int
           or row['relative_ticks_90k'] < 0 for i, row in enumerate(frames)):
        raise ValueError('pose_gap_invalid_frames')
    ticks = [row['relative_ticks_90k'] for row in frames]
    if any(a >= b for a, b in zip(ticks, ticks[1:])):
        raise ValueError('pose_gap_invalid_ticks')
    if (not initial or len(initial) > max_selected
            or any(type(i) is not int or not 0 <= i < len(frames) for i in initial)
            or any(a >= b for a, b in zip(initial, initial[1:]))):
        raise ValueError('pose_gap_invalid_indices')
    by_image = {}
    for row in bindings:
        if type(row) is not dict:
            raise ValueError('pose_gap_invalid_binding')
        image, index, tick = row.get('image'), row.get('source_index'), row.get('relative_ticks_90k')
        if (type(image) is not str or not image or image in by_image
                or type(index) is not int or index not in initial
                or type(tick) is not int or tick != ticks[index]
                or index in by_image.values()):
            raise ValueError('pose_gap_invalid_binding')
        by_image[image] = index
    if set(by_image.values()) != set(initial):
        raise ValueError('pose_gap_incomplete_binding')
    flags = motion.get('speed_outliers')
    if type(flags) is not list:
        raise ValueError('pose_gap_invalid_flags')
    flagged = set()
    for row in flags:
        if type(row) is not dict or type(row.get('image')) is not str or row['image'] not in by_image:
            raise ValueError('pose_gap_invalid_flag')
        index = by_image[row['image']]
        if index == initial[0] or index in flagged:
            raise ValueError('pose_gap_invalid_flag')
        flagged.add(index)
    remaining = min(max_additions, max_selected - len(initial))
    additions, intervals = [], []
    for position, b in enumerate(initial[1:], 1):
        if b not in flagged:
            continue
        a = initial[position - 1]
        count = min(3, b - a - 1, remaining)
        chosen = []
        for k in range(1, count + 1):
            # Integer arithmetic avoids float precision and makes tie breaking explicit.
            target = ticks[a] * (count + 1 - k) + ticks[b] * k
            low = chosen[-1] + 1 if chosen else a + 1
            high = b - (count - k) - 1
            chosen.append(min(range(low, high + 1),
                              key=lambda i: (abs(ticks[i] * (count + 1) - target), i)))
        additions.extend(chosen)
        remaining -= count
        intervals.append({'first_index': a, 'second_index': b, 'added_indices': chosen,
                          'status': 'adjacent_unresolved' if b - a == 1 else
                                    'budget_unresolved' if count == 0 else 'planned_unverified'})
    return {'selected_indices': sorted(initial + additions), 'added_indices': additions,
            'intervals': intervals, 'execution_qualified': False,
            'note': 'Selection only; flagged intervals and resulting poses are not verified.'}


def select_overlaps(frames, initial, measure, check, *, maximum=240, min_support=30, min_retention=.35):
    """Subdivide weakest gaps deterministically, measuring actual frame pairs only."""
    n = len(frames)
    if (n < 2 or type(maximum) is not int or not 2 <= maximum <= 240
            or type(min_support) is not int or min_support < 1
            or type(min_retention) not in (int, float)
            or not math.isfinite(min_retention) or not 0 < min_retention <= 1):
        raise ValueError('overlap_sampling_limits')
    if (any(type(row.get('index')) is not int or row['index'] != i
            or type(row.get('relative_ticks_90k')) is not int or row['relative_ticks_90k'] < 0
            for i, row in enumerate(frames))
            or any(b['relative_ticks_90k'] <= a['relative_ticks_90k'] for a,b in zip(frames,frames[1:]))):
        raise ValueError('overlap_sampling_source_order')
    selected = sorted(set(initial))
    if (len(selected) != len(initial) or len(selected) > maximum or not selected
            or selected[0] != 0 or selected[-1] != n-1
            or any(type(i) is not int or not 0 <= i < n for i in selected)):
        raise ValueError('overlap_sampling_initial_indices')
    cache = {}
    def evaluate(a, b):
        check()
        if (a,b) not in cache:
            result = dict(measure(a,b))
            total, stable = result.get('detected'), result.get('stable')
            if (type(total) is not int or type(stable) is not int or not 0 <= stable <= total):
                raise ValueError('overlap_sampling_invalid_measurement')
            ratio = stable / total if total else 0.0
            causes = []
            if total < min_support: causes.append('insufficient_detected_features')
            if stable < min_support: causes.append('low_stable_count')
            if ratio < min_retention: causes.append('low_retention')
            result.update(first_index=a, second_index=b,
                          first_ticks_90k=frames[a]['relative_ticks_90k'],
                          second_ticks_90k=frames[b]['relative_ticks_90k'],
                          retention=ratio, supported=not causes, causes=causes)
            cache[a,b] = result
        return cache[a,b]
    def intervals(): return [evaluate(a,b) for a,b in zip(selected,selected[1:])]
    baseline = intervals()
    additions = []
    while len(selected) < maximum:
        weak = [r for r in intervals() if not r['supported'] and r['second_index']-r['first_index'] > 1]
        if not weak: break
        # Largest elapsed weak interval first; lowest retention, then earliest index break ties.
        r = min(weak, key=lambda x: (-(x['second_ticks_90k']-x['first_ticks_90k']), x['retention'], x['first_index']))
        a,b = r['first_index'],r['second_index']
        target = (frames[a]['relative_ticks_90k']+frames[b]['relative_ticks_90k']) / 2
        mid = min(range(a+1,b), key=lambda i: (abs(frames[i]['relative_ticks_90k']-target),i))
        selected.append(mid);selected.sort();additions.append({'index':mid,'split': [a,b]})
    final = intervals()
    for r in final:
        if not r['supported']:
            r['unresolved_reason'] = ('adjacent_source_frames' if r['second_index']-r['first_index']==1 else 'view_budget_exhausted')
    return selected, {'baseline': baseline, 'final': final, 'additions': additions,
                      'max_views': maximum, 'min_stable': min_support, 'min_retention': min_retention}


def _digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''): h.update(block)
    return h.hexdigest()


def run(capture_path, prepared_path, output, *, maximum=240, min_support=30, min_retention=.35,
        timeout=120, cancellation=lambda: False):
    if (type(timeout) not in (int,float) or not math.isfinite(timeout)
            or not 0 < timeout <= 120 or not callable(cancellation)):
        raise ValueError('overlap_sampling_runtime_limits')
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    initialize_route_cpu_runtime()
    import cv2
    import numpy as np
    from motor_worker.browser_teach import validate_browser, decoded_browser
    from scripts.pilot.route_masks import capture_exclusions
    from scripts.pilot.video_observations import track_source_points
    from scripts.pilot.resource_guard import windows_memory
    cv2.setNumThreads(2)
    started=time.monotonic(); last_guard=0.; minima=[float('inf'),float('inf')]
    def check():
        nonlocal last_guard
        now=time.monotonic()
        if cancellation(): raise RuntimeError('overlap_sampling_cancelled')
        if now-started > timeout: raise RuntimeError('overlap_sampling_timeout')
        if now-last_guard >= .5:
            m=windows_memory();ram=m['availableRamBytes'];commit=m['commitLimitBytes']-m['committedBytes']
            minima[0]=min(minima[0],ram);minima[1]=min(minima[1],commit);last_guard=now
            if min(ram,commit)<4.5*1024**3: raise RuntimeError('overlap_sampling_memory_guard')
    check(); capture_path=Path(capture_path); prepared_path=Path(prepared_path); output=Path(output)
    inputs=[capture_path/n for n in ('video.h264','manifest.json','frames.jsonl','inputs.jsonl','COMPLETE')]+[prepared_path]
    before={str(p):_digest(p) for p in inputs};check()
    capture=validate_browser(capture_path);check()
    prepared=json.loads(prepared_path.read_text(encoding='utf-8'))
    if prepared.get('source_manifest_sha256') != before[str(capture_path/'manifest.json')]: raise ValueError('overlap_sampling_source_binding')
    initial=[]
    for p in prepared['images']:
        i=p['source_index']; row=capture.frames[i]
        if (p['relative_ticks_90k']!=row['relative_ticks_90k'] or p['source_access_unit_sha256']!=row['sha256']):
            raise ValueError('overlap_sampling_frame_binding')
        initial.append(i)
    width,height=capture.geometry;scale=min(1.,640/max(width,height));size=(round(width*scale),round(height*scale))
    if len(capture.frames)*size[0]*size[1]>240*1024**2: raise ValueError('overlap_sampling_cache_budget')
    mask=np.full((size[1],size[0]),255,np.uint8);mask[:int(size[1]*.2)]=0
    for x1,y1,x2,y2 in capture_exclusions('game',capture.manifest):
        mask[int(y1*size[1]):int(y2*size[1]),int(x1*size[0]):int(x2*size[0])]=0
    images=[]
    for row,frame in decoded_browser(capture):
        check()
        if row['index']!=len(images): raise ValueError('overlap_sampling_decode_order')
        images.append(cv2.resize(frame.to_ndarray(format='gray'),size,interpolation=cv2.INTER_AREA))
    if len(images)!=len(capture.frames): raise ValueError('overlap_sampling_decode_count')
    features={}
    def measure(a,b):
        if a not in features:
            p=cv2.goodFeaturesToTrack(images[a],800,.007,8,mask=mask)
            features[a]=np.empty((0,2),np.float32) if p is None else p[:,0]
        points=features[a];moved,good=track_source_points(images[a],images[b],points,tolerance=1.0)
        finite=np.isfinite(moved).all(axis=1);inside=finite&(moved[:,0]>=0)&(moved[:,0]<size[0])&(moved[:,1]>=0)&(moved[:,1]<size[1]); safe=np.where(finite[:,None],moved,0)
        x=np.clip(np.rint(safe[:,0]).astype(int),0,size[0]-1);y=np.clip(np.rint(safe[:,1]).astype(int),0,size[1]-1);good &= inside & (mask[y,x]>0)
        return {'detected':len(points),'stable':int(good.sum())}
    indices,results=select_overlaps(capture.frames,initial,measure,check,maximum=maximum,min_support=min_support,min_retention=min_retention)
    after={str(p):_digest(p) for p in inputs};check()
    if before!=after: raise RuntimeError('overlap_sampling_source_changed')
    def summary(rows):
        count=sum(r['supported'] for r in rows)
        unknown=sum((r['second_ticks_90k']-r['first_ticks_90k'])/90000 for r in rows if not r['supported'])
        return {'intervals':len(rows),'supported':count,'supported_fraction':count/len(rows) if rows else None,
                'weak_duration_seconds':unknown}
    report={'schema':'sphere-overlap-sampling-experiment-v1','source_hashes_before':before,'source_hashes_after':after,'input_unchanged':True,
            'initial_views':len(initial),'selected_views':len(indices),'initial_indices':initial,'selected_indices':indices,
            'selected_timestamps_90k':[capture.frames[i]['relative_ticks_90k'] for i in indices],
            'tracking_resolution':size,'source_frames':len(capture.frames),'decoded_frames':len(images),
            'baseline_summary':summary(results['baseline']),'final_summary':summary(results['final']),
            'results':results,'seconds':time.monotonic()-started,'minimum_sampled_available_ram_bytes':minima[0],
            'minimum_sampled_commit_headroom_bytes':minima[1],'metric_pose_known':False,'navigation_qualified':False,
            'note':'Pair support is not pose accuracy; selection and evaluation use same recording and same test.'}
    output.mkdir(parents=True,exist_ok=False)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--capture',required=True,type=Path);ap.add_argument('--prepared',required=True,type=Path);ap.add_argument('--output',required=True,type=Path);ap.add_argument('--max-views',type=int,default=240);ap.add_argument('--min-support',type=int,default=30);ap.add_argument('--min-retention',type=float,default=.35);args=ap.parse_args()
    result=run(args.capture,args.prepared,args.output,maximum=args.max_views,min_support=args.min_support,min_retention=args.min_retention)
    print(json.dumps({k:result[k] for k in ('initial_views','selected_views','baseline_summary','final_summary','seconds')}))
if __name__=='__main__':main()
