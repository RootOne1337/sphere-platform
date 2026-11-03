"""Bounded local diagnostic frames; no input authority or hot-path disk writes."""
import hashlib
import io
import json
import math
import re
import threading
import time
import uuid
import zipfile
from collections import deque
from pathlib import Path

CONFIRMATION_TELEMETRY_POLICY = 'distinct_current_pose_3of5_source_bound_1second_v1'
MOTION_TELEMETRY_POLICY = 'current_inlier_center_subpixel_0p5px_1pct_moving_step_v2'
SOURCE_MOTION_TELEMETRY_POLICY = 'bounded_source_arc_preimage_local_speed_v1'


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
    for name, maximum in (('verifiedInliersBeforeTemporalGate', 4096),
                          ('confirmationValidCount', 5), ('confirmationObservationCount', 5)):
        number = value.get(name)
        if type(number) is int and 0 <= number <= maximum:
            result[name] = number
    for name, maximum in (('verifiedMedianErrorPx', 60000.),
                          ('motionCenterDeltaUnits', 1e12), ('motionProgressDeltaUnits', 1e12),
                          ('motionLimitUnits', 1e12), ('motionTurnRadians', math.pi),
                          ('motionSubpixelDeltaPx', 60000.), ('motionSubpixelCapUnits', 1e12),
                          ('motionBaseLimitUnits', 1e12), ('motionAllowanceUnits', 1e12),
                          ('motionReferenceSeconds', 86400.), ('motionObservedSourceSpeed', 1e12),
                          ('motionSourceArcLowUnits', 1e12), ('motionSourceArcHighUnits', 1e12),
                          ('motionSourceArcEpsilonUnits', 1e12), ('motionSourceLimitUnits', 1e12),
                          ('motionSourceMaxSpeedUnitsPerSecond', 1e12),
                          ('motionSourceFirstSeconds', 86400.), ('motionSourceLastSeconds', 86400.),
                          ('motionSourceWindowStartSeconds', 86400.), ('motionSourceWindowEndSeconds', 86400.)):
        number = value.get(name)
        if type(number) in {int, float} and math.isfinite(number) and 0 <= number <= maximum:
            result[name] = number
    if value.get('confirmationPolicy') == CONFIRMATION_TELEMETRY_POLICY:
        result['confirmationPolicy'] = CONFIRMATION_TELEMETRY_POLICY
    if value.get('motionConsistencyPolicy') == MOTION_TELEMETRY_POLICY:
        result['motionConsistencyPolicy'] = MOTION_TELEMETRY_POLICY
    if type(value.get('motionSubpixelEligible')) is bool:
        result['motionSubpixelEligible'] = value['motionSubpixelEligible']
    if type(value.get('motionSourceEnvelopeEligible')) is bool:
        result['motionSourceEnvelopeEligible'] = value['motionSourceEnvelopeEligible']
    if value.get('motionSourcePolicy') == SOURCE_MOTION_TELEMETRY_POLICY:
        result['motionSourcePolicy'] = SOURCE_MOTION_TELEMETRY_POLICY
    return result


class RuntimeMetadataRing:
    """One owned latest-snapshot writer; offers never perform filesystem I/O.

    Every admitted offer stays in a bounded 64-row memory ring. Disk snapshots
    are coalesced to at most one per second, so alternating pose outcomes are
    retained even when input cadence is faster than the writer. Close drops
    pending work and joins; diagnostics never grant or repeat input authority.
    """
    FILE = 'navigation-runtime-diagnostic.json'
    MAX_ROWS = 64
    MAX_BYTES = 64 * 1024
    _owners = {}
    _owners_lock = threading.Lock()

    def __init__(self, job_or_path, *, clock=time.monotonic):
        target = Path(job_or_path)
        if target.name == self.FILE:
            target = target.parent
        if target.is_symlink() or target.is_junction() or not target.is_dir():
            raise ValueError('runtime_diagnostic_path')
        self.folder = target.resolve(strict=True)
        self.path = self.folder / self.FILE
        self.clock = clock
        self.identity = uuid.uuid4().hex
        self.began = clock()
        self.rows = deque(maxlen=self.MAX_ROWS)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._closed = False
        self.write_errors = 0
        self.writes = 0
        with self._owners_lock:
            if self.path in self._owners:
                raise ValueError('runtime_diagnostic_writer_owned')
            self._owners[self.path] = self
        self._thread = threading.Thread(target=self._run, name='route-metadata-'+self.identity[:8], daemon=True)
        try:
            self._thread.start()
        except BaseException:
            with self._owners_lock:
                self._owners.pop(self.path, None)
            raise

    @staticmethod
    def _get(value, key):
        return value.get(key) if isinstance(value, dict) else getattr(value, key, None)

    def offer(self, *, pose=None, diagnostic=None, plan=None, compute_ms=None, source_binding=None, sequence=None):
        try:
            now = self.clock()
            if not math.isfinite(now) or self._closed:
                return False
            source = diagnostic.get('sourceFamily', 'unknown') if isinstance(diagnostic, dict) else 'unknown'
            reason = self._get(pose, 'reason')
            bounded = bounded_localization_diagnostic(diagnostic, reason=reason, source_family=source)
            row = dict(elapsedMs=max(0., (now-self.began)*1000),
                       poseState=self._get(pose, 'state') if self._get(pose, 'state') in {'unknown','confirming','localized'} else 'unknown',
                       poseReason=bounded['poseReason'], localizationDiagnostic=bounded)
            number = self._get(pose, 'inliers')
            if type(number) is int and 0 <= number <= 4096:
                row['inliers'] = number
            sequence = self._get(pose, 'receiver_sequence') if sequence is None else sequence
            if type(sequence) is int and 0 <= sequence <= 2**53-1:
                row['sequence'] = sequence
            epoch = self._get(pose, 'epoch') or self._get(pose, 'capture_epoch')
            if type(epoch) is str and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', epoch):
                row['captureEpoch'] = epoch
            if type(compute_ms) in {int, float} and math.isfinite(compute_ms) and 0 <= compute_ms <= 60000:
                row['computeMs'] = compute_ms
            if isinstance(plan, dict):
                safe = {}
                for key, allowed in (('phase', {'waiting','active','following','stopped','arrived','recovering'}),
                                     ('pedal', {'coast','throttle','forward','brake','reverse'})):
                    if type(plan.get(key)) is str and plan[key] in allowed:
                        safe[key] = plan[key]
                reason = plan.get('reason')
                if type(reason) is str and re.fullmatch(r'(?:vehicle|route|walk)_[a-z_]{1,72}', reason):
                    safe['reason'] = reason
                for key, maximum in (('progressFraction',1.),('targetSpeedKmh',350.),('observedSpeedKmh',350.)):
                    value = plan.get(key)
                    if type(value) in {int,float} and math.isfinite(value) and 0 <= value <= maximum:
                        safe[key] = value
                row['plan'] = safe
            if isinstance(source_binding, dict):
                safe = {}
                for key in ('geometry_sha256','source_manifest_sha256','reconstruction_input_sha256'):
                    value = source_binding.get(key)
                    if type(value) is str and re.fullmatch('[0-9a-f]{64}',value):
                        safe[key] = value
                row['sourceBinding'] = safe
            if not self._lock.acquire(blocking=False):
                return False
            try:
                if self._closed:
                    return False
                self.rows.append(row)
                self._wake.set()
            finally:
                self._lock.release()
            return True
        except Exception:
            return False

    def _write_snapshot(self, rows):
        if self.path.is_symlink() or self.path.is_junction() or self.path.resolve().parent != self.folder:
            raise ValueError('runtime_diagnostic_path')
        body = dict(schema='sphere-navigation-runtime-metadata-v1', scope='local_metadata_only',
                    sessionId=self.identity, physicalActions=0, executionQualified=False, rows=rows)
        raw = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        while len(raw) >= self.MAX_BYTES and rows:
            rows = rows[1:]
            body['rows'] = rows
            raw = json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
        temporary = self.folder / ('.navigation-runtime-diagnostic.'+self.identity+'.tmp')
        if temporary.exists() and (temporary.is_symlink() or temporary.is_junction()):
            raise ValueError('runtime_diagnostic_path')
        try:
            with temporary.open('wb') as stream:
                stream.write(raw)
            if self.path.is_symlink() or self.path.is_junction():
                raise ValueError('runtime_diagnostic_path')
            temporary.replace(self.path)
        finally:
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink(missing_ok=True)

    def _run(self):
        next_write = -math.inf
        try:
            while not self._stop.is_set():
                self._wake.wait(.1)
                if self._stop.is_set():
                    break
                now = time.monotonic()
                if not self._wake.is_set() or now < next_write:
                    self._stop.wait(min(.1, max(0., next_write-now)))
                    continue
                with self._lock:
                    rows = list(self.rows)
                    self._wake.clear()
                next_write = now + 1.
                try:
                    self._write_snapshot(rows)
                    self.writes += 1
                except Exception:
                    self.write_errors += 1
        finally:
            with self._owners_lock:
                if self._owners.get(self.path) is self:
                    self._owners.pop(self.path, None)

    def close(self):
        try:
            with self._lock:
                self._closed = True
            self._stop.set()
            self._wake.set()
            self._thread.join(timeout=2.)
            if not self._thread.is_alive():
                self.rows.clear()
        except Exception:
            pass


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
