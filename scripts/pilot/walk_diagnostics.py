"""Bounded local diagnostic frames; no input authority or hot-path disk writes."""
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile


def bounded_localization_diagnostic(value, *, reason=None, source_family='unknown'):
    """Allowlisted scalar/small-count telemetry, never descriptors or authority."""
    value = value if isinstance(value, dict) else {}
    methods = {'not_attempted', 'descriptor_pnp', 'map_anchored_flow', 'measured_reference_lk'}
    reasons = {'route_binding_retired', 'route_observation_gap', 'route_scene_geometry_or_age_unqualified',
               'route_repeated_rgb_not_independent', 'route_frame_expired_during_localization',
               'route_pose_not_verified', 'route_progress_ambiguous', 'route_outside_observed_corridor',
               'route_pose_discontinuity', 'relative_camera_pose_not_clearance_or_arrival'}
    def integers(name, maximum):
        rows = value.get(name)
        if (type(rows) not in {list, tuple} or len(rows) > 8
                or any(type(item) is not int or not 0 <= item <= maximum for item in rows)):
            return None
        return list(rows)
    candidates = integers('candidateReferenceIndices', 255)
    retained = integers('flowRetainedByCandidate', 65536)
    verified = value.get('verifiedCandidateCount')
    method = value.get('method')
    result = dict(schema='sphere-localization-observation-diagnostic-v1',
        method=method if type(method) is str and method in methods else 'not_attempted',
        sourceFamily=source_family if type(source_family) is str and source_family in {'reference_lk', 'legacy_sparse'} else 'unknown',
        poseReason=reason if type(reason) is str and reason in reasons else 'unavailable',
        candidateCount=len(candidates) if candidates is not None else None,
        candidateReferenceIndices=candidates, flowRetainedByCandidate=retained,
        retainedLkCount=sum(retained) if retained is not None else None,
        maxRetainedLkCount=max(retained, default=0) if retained is not None else None,
        verifiedCandidateCount=verified if type(verified) is int and 0 <= verified <= 8 else None)
    for name in ('featurePreparationMs', 'featureExtractionMs', 'coarseSearchMs',
                 'candidateMatchPnPMs', 'flowPnPMs'):
        number = value.get(name)
        if type(number) in {int, float} and math.isfinite(number) and 0 <= number <= 60000:
            result[name] = number
    for name in ('flowCandidates', 'flowRetained', 'queryFeatures', 'descriptorCandidates'):
        number = value.get(name)
        if type(number) is int and 0 <= number <= 65536:
            result[name] = number
    return result


def retain(folder, suffix, *, count, byte_limit, protected):
    folder=Path(folder).resolve()
    files=[]
    for path in folder.iterdir():
        if not re.fullmatch(r'[0-9a-f]{32}\.'+re.escape(suffix),path.name):continue
        if path.is_symlink() or path.resolve().parent!=folder or not path.is_file():
            raise ValueError('diagnostic_retention_path')
        files.append(path)
    files.sort(key=lambda p:(p.stat().st_mtime_ns,p.name))
    size=sum(p.stat().st_size for p in files)
    while len(files)>count or size>byte_limit:
        old=next((p for p in files if p.name!=protected),None)
        if old is None:raise ValueError('diagnostic_retention_quota')
        size-=old.stat().st_size;old.unlink();files.remove(old)


class WalkFrameArchive:
    MAX_BYTES=2*1024**2
    MAX_FRAMES=12
    FIRST_FRAMES=2

    def __init__(self, job, identity, *, clock,geometry_sha256=None,capture_epoch=None):
        if not re.fullmatch('[0-9a-f]{32}',identity):raise ValueError('diagnostic_identity')
        self.job,self.identity,self.clock=Path(job),identity,clock
        self.began=clock();self.last=-1e12;self.rows=[];self.bytes=0;self.result=None
        self.binding=dict(geometrySha256=geometry_sha256,captureEpoch=capture_epoch,querySize=[960,540])

    def offer(self, raw, *, sequence, pose, plan, method, compute_ms, diagnostic=None):
        now=self.clock()
        if now-self.last<.5 or not isinstance(raw,bytes) or len(raw)>384*1024:return
        self.last=now
        row=dict(sequence=sequence,elapsedMs=(now-self.began)*1000,jpegSha256=hashlib.sha256(raw).hexdigest(),
            poseState=pose.state,poseReason=pose.reason,inliers=pose.inliers,center=pose.center,rotation=pose.rotation,
            segment=pose.segment,method=method,computeMs=compute_ms,
            plan=None if plan is None else {k:plan.get(k) for k in ('phase','reason','stick','progressFraction','motionActive','motionSeconds')})
        if diagnostic is not None:
            source = diagnostic.get('sourceFamily', 'unknown') if isinstance(diagnostic, dict) else 'unknown'
            row['localizationDiagnostic'] = bounded_localization_diagnostic(
                diagnostic, reason=pose.reason, source_family=source)
        if plan is not None and plan.get('schema') == 'sphere-vehicle-plan-v1':
            row['plan'] = {key: plan.get(key) for key in (
                'schema', 'phase', 'reason', 'pedal', 'steering', 'progressFraction',
                'motionActive', 'motionSeconds', 'targetSpeedKmh', 'observedSpeedKmh',
                'speedAccepted', 'maxSpeedKmh', 'targetViewCamera', 'maxDecisionAgeMs', 'maxAnswerHoldMs')}
        self.rows.append((raw,row));self.bytes+=len(raw)
        while len(self.rows)>self.MAX_FRAMES or self.bytes>self.MAX_BYTES-64*1024:
            # Preserve acquisition evidence alongside the recent failure tail.
            # Two admitted JPEGs fit below the byte quota even at their maximum.
            self.bytes-=len(self.rows.pop(min(self.FIRST_FRAMES, len(self.rows)-1))[0])

    def finish(self):
        if self.result is not None:return self.result
        if not self.rows:return dict(state='empty',frames=0,bytes=0)
        folder=self.job/'walk-diagnostics'
        if folder.is_symlink():raise ValueError('diagnostic_archive_path')
        folder.mkdir(exist_ok=True);path=folder/(self.identity+'.zip')
        if path.is_symlink():raise ValueError('diagnostic_archive_path')
        if path.exists():return dict(state='existing',frames=0,bytes=path.stat().st_size)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',compression=zipfile.ZIP_STORED) as archive:
            for raw,row in self.rows:archive.writestr(f"frame-{row['sequence']:06d}.jpg",raw)
            archive.writestr('metadata.json',json.dumps(dict(schema='sphere-walk-frame-archive-v1',
                physicalActions=0,scope='local_processor_diagnostic',inputAuthority='browser_owner',id=self.identity,
                retentionPolicy='first2_and_recent_tail',binding=self.binding,frames=[r for _,r in self.rows]),allow_nan=False))
        raw=data.getvalue()
        if len(raw)>self.MAX_BYTES:raise ValueError('diagnostic_archive_quota')
        with path.open('xb') as file:file.write(raw)
        retain(folder,'zip',count=16,byte_limit=32*1024**2,protected=path.name)
        self.result=dict(state='saved',frames=len(self.rows),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        self.rows.clear();self.bytes=0
        return self.result
