"""Local self-service route assets and bounded, read-only RGB localization.

The reconstruction job capability authorizes access before these methods run.
No Android connection, model, native input, external URL or frame archive exists
here. A browser must display results on the exact query frame, within its own
freshness budget; server-receive age is not Android capture latency.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, replace
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r'^[0-9a-f]{32}$')
TERMINAL = {'ready', 'failed', 'rejected', 'cancelled'}


def checked_json(path, maximum=65536):
    if path.is_symlink() or path.parent.is_symlink() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('route_asset_quota_or_symlink')
    return json.loads(path.read_bytes())


def digest_file(path):
    if path.is_symlink():
        raise ValueError('route_source_symlink')
    with path.open('rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def route_resource_profile(job, kind='features'):
    """Budget the bounded CPU task; dense reconstruction keeps its own guard.

    Source validation can retain the compressed video. Account for three
    copies, two full RootSIFT feature tables (256*2048*128 float32) and a
    1.5 GiB runtime allowance, in addition to 4 GiB left for the host.
    Unknown inputs keep the previous conservative 12 GiB floor.
    """
    if kind == 'live':
        # Fixed 960x540 query, 4 MiB map, one observation in flight, no model.
        # A real RGB/HTTP process (including source-video decode) peaked at
        # 204 MiB working set / 719 MiB commit on this runtime. Keep 4 GiB
        # available for the host plus a conservative 768 MiB task allowance.
        return dict(kind='route_live', minRamGiB=4.75, hostReserveGiB=4., taskReserveGiB=.75, maxMapBytes=4*1024**2,
                    maxFrameBytes=384*1024, minDiskGiB=1., modelLoaded=False, maxCommitPercent=85)
    if kind != 'features':
        raise ValueError('route_resource_profile')
    video = job/'input/video.h264'
    size = video.stat().st_size if video.is_file() and not video.is_symlink() else None
    if size is None or not 0 < size <= 2**31:
        required = 12.
    else:
        tables = 2*256*2048*128*4
        required = max(6., math.ceil((4+1.5+(3*size+tables)/1024**3)*4)/4)
    return dict(kind='route_features', minRamGiB=required, hostReserveGiB=4.,
                sourceVideoBytes=size, maxViews=256, maxFeaturesPerView=2048,
                modelLoaded=False, maxCommitPercent=85)


def resource_checkpoint(folder, *, profile=None):
    if (folder/'CANCEL').exists():
        raise RuntimeError('cancelled')
    snapshot = collect(ROOT)
    minimum = 12 if profile is None else profile['minRamGiB']
    floor = 4.75 if profile is not None and profile.get('kind') == 'route_live' else 6
    if not isinstance(minimum, (int, float)) or isinstance(minimum, bool) or not floor <= minimum <= 16:
        raise ValueError('route_resource_profile')
    # Live matching reads an already prepared, bounded map. It neither exports
    # video nor builds a scene. Its bounded summaries need at most 64*512 KiB
    # per job; retain 1 GiB disk headroom instead of the heavy-build 20 GiB.
    disk_minimum = 20 if profile is None else profile.get('minDiskGiB', 20)
    if (type(disk_minimum) not in {int, float} or not 1 <= disk_minimum <= 20
            or disk_minimum < 20 and profile.get('kind') != 'route_live'):
        raise ValueError('route_resource_profile')
    findings = evaluate(snapshot, min_ram_gib=minimum, min_disk_gib=disk_minimum)
    if findings:
        if folder.is_dir():
            write_json(folder/'resource-refusal.json', dict(snapshot=snapshot, findings=findings,
                       profile=profile or dict(kind='legacy_experiment', minRamGiB=12)))
        raise RuntimeError('resource_guard')


class RouteWorkspaces:
    def __init__(self, folder, python, *, clock=time.perf_counter):
        self.folder, self.python, self.clock = folder, python, clock
        self.live = None
        self.retired = {}
        for state in folder.glob('*/navigation/*/state.json'):
            if checked_json(state)['phase'] not in TERMINAL:
                write_json(state, dict(phase='failed', error='route_service_restarted'))

    def current(self, job):
        if job.is_symlink() or not job.resolve().is_relative_to(self.folder.resolve()) or (job/'navigation').is_symlink():
            raise ValueError('route_preparation_path')
        link = job/'navigation/active.json'
        if not link.exists():
            return None
        identity = checked_json(link).get('id')
        if not isinstance(identity, str) or not ID.fullmatch(identity):
            raise ValueError('route_preparation_id')
        folder = job/'navigation'/identity
        if folder.is_symlink() or not folder.resolve().is_relative_to(job.resolve()):
            raise ValueError('route_preparation_path')
        return folder

    def status(self, job):
        folder = self.current(job)
        if folder is None:
            return dict(phase='not_prepared', executionQualified=False,
                        resourceProfile=route_resource_profile(job))
        result = dict(checked_json(folder/'state.json'), id=folder.name, executionQualified=False,
                      resourceProfile=route_resource_profile(job))
        if result['phase'] == 'ready' and not (folder/'receipt.json').is_file():
            return dict(result, phase='rejected', error='route_receipt_missing')
        if result['phase'] in {'ready', 'rejected'} and (folder/'receipt.json').exists():
            receipt = checked_json(folder/'receipt.json')
            if (receipt.get('geometry_sha256') != digest_file(job/'geometry.json')
                    or receipt.get('source_capture_sha256') != digest_file(job/'input/manifest.json')):
                return dict(result, phase='rejected', error='route_source_changed')
            support = receipt.get('map_support') or {}
            coverage = receipt.get('source_coverage') or {}
            # Keep the measured cause available even for a rejected result.
            # A new preflight failure does not erase this previous attempt.
            result['summary'] = {key: receipt.get(key) for key in
                ('cameras', 'landmarks', 'first_seconds', 'last_seconds', 'source_coverage',
                 'map_support', 'camera_trace_only')}
            if (support.get('all_reference_neighborhoods_supported') is not True
                    or support.get('all_reference_intervals_observed') is not True
                    or coverage.get('endpoints_observed') is not True):
                return dict(result, phase='rejected', error='route_map_has_unobserved_sections')
            from motor_worker.route_localization import pipeline_id
            if receipt.get('pipeline_sha256') != pipeline_id():
                return dict(result, phase='rejected', error='route_feature_runtime_mismatch')
        return result

    def preparing(self, job):
        return self.status(job)['phase'] not in TERMINAL | {'not_prepared'}

    def prepare(self, job, body):
        self._expire()
        self.current(job)  # Validate the fixed root before creating any directory.
        identity = body.get('id') if type(body) is dict else None
        if not isinstance(identity, str) or not ID.fullmatch(identity) or set(body) != {'id'}:
            raise ValueError('route_preparation_intent')
        folder = job/'navigation'/identity
        if folder.exists():
            # Repeated intent reads its own outcome; never repeat a lost start.
            return dict(checked_json(folder/'state.json'), id=identity, executionQualified=False)
        current = self.status(job)
        if current.get('error') == 'route_map_has_unobserved_sections':
            summary = current.get('summary', {})
            if ((summary.get('source_coverage') or {}).get('endpoints_observed') is False
                    or (summary.get('map_support') or {}).get('all_reference_intervals_observed') is False):
                # Exporting identical poses cannot fill a missing time interval.
                # Preserve the old attempt and do not spend another intent.
                raise ValueError('route_camera_recovery_required')
        if self.preparing(job) or self.live is not None:
            raise ValueError('route_workspace_busy')
        if len(list((job/'navigation').glob('*/intent.json'))) >= 3:
            raise ValueError('route_preparation_attempt_quota')
        profile = route_resource_profile(job)
        resource_checkpoint(job, profile=profile)
        folder.mkdir(parents=True)
        write_json(folder/'intent.json', dict(id=identity, scope='READ_ONLY_ROUTE_ASSETS', physicalActions=0,
                                           resourceProfile=profile))
        write_json(folder/'state.json', dict(phase='preparing'))
        write_json(job/'navigation/active.json', dict(id=identity))
        with (folder/'worker.private.log').open('xb') as log:
            try:
                process = subprocess.Popen([str(self.python), '-m', 'scripts.pilot.prepare_route_workspace',
                    '--job', str(job), '--attempt', identity], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except Exception:
                write_json(folder/'state.json', dict(phase='failed', error='route_start_not_confirmed'))
                raise
        threading.Thread(target=self._monitor, args=(folder, process, profile), daemon=True).start()
        return self.status(job)

    def _monitor(self, folder, process, profile=None):
        deadline = time.monotonic()+330
        while process.poll() is None:
            time.sleep(3)
            try:
                resource_checkpoint(folder, profile=profile)
                if time.monotonic() > deadline:
                    raise RuntimeError('route_preparation_timeout')
                if (folder/'worker.private.log').stat().st_size > 8*1024**2:
                    raise RuntimeError('route_log_quota')
            except RuntimeError as exc:
                process.kill()  # This CPU exporter has no child executables.
                process.wait(10)
                write_json(folder/'state.json', dict(phase='failed', error=str(exc)))
                return
        if checked_json(folder/'state.json')['phase'] not in TERMINAL:
            write_json(folder/'state.json', dict(phase='failed', error='route_export_not_confirmed'))

    def _expire(self):
        now = self.clock()
        self.retired = {identity: deadline for identity, deadline in self.retired.items() if deadline > now}
        if self.live and self.clock() >= self.live['deadline']:
            self._finish_diagnostics(self.live)
            self.retired[self.live['id']] = now + 600
            self.live = None

    @staticmethod
    def _finish_diagnostics(session):
        try:return session['frame_archive'].finish() if session.get('frame_archive') else None
        except (OSError,ValueError):return dict(state='unconfirmed',frames=0,bytes=0)

    def live_status(self):
        self._expire()
        if self.live is None:
            return dict(phase='idle', physicalActions=0)
        return dict(phase='observing', id=self.live['id'], job=self.live['job'],
                    observations=self.live['observations'], secondsRemaining=max(0, self.live['deadline']-self.clock()),
                    physicalActions=0)

    def start_live(self, job, body, *, mode='live'):
        import cv2 as cv
        from motor_worker.route_localization import SparseRoute
        from motor_worker.route_tracking import AnchoredRouteLocalizer

        if (mode not in {'live','recorded_replay'} or type(body) is not dict or set(body) != {'id', 'captureEpoch', 'width', 'height', 'sceneConfirmed'}
                or not isinstance(body['id'], str) or not ID.fullmatch(body['id'])
                or not isinstance(body['captureEpoch'], str)
                or not re.fullmatch(r'[0-9a-f-]{16,64}', body['captureEpoch'])
                or body['sceneConfirmed'] is not True):
            raise ValueError('route_live_confirmation_or_binding')
        self._expire()
        if self.live is not None:
            if (self.live['id'] == body['id'] and self.live['job'] == job.name and self.live['binding'] == body
                    and self.live.get('mode','live')==mode):
                return self.live_status()
            raise ValueError('one_live_route_observer_only')
        if body['id'] in self.retired or len(self.retired) >= 2048:
            raise ValueError('route_session_retired_or_quota')
        if self.status(job)['phase'] != 'ready':
            raise ValueError('route_assets_not_ready')
        resource_checkpoint(job, profile=route_resource_profile(job, 'live'))
        # One observation is processed at a time. Bound native parallelism while
        # leaving headroom inside the 250 ms receiver-age budget for SIFT/PnP.
        cv.setNumThreads(4)
        folder = self.current(job)
        receipt = checked_json(folder/'receipt.json')
        route = SparseRoute.load(folder/'route.json', sha256=receipt['sha256'])
        if (type(body['width']) is not int or type(body['height']) is not int
                or not 128 <= body['width'] <= 8192 or not 128 <= body['height'] <= 8192
                or body['width']*body['height'] > 8*1024**2
                or body['width']*route.profile.height != body['height']*route.profile.width):
            raise ValueError('route_live_geometry_changed')
        # JPEG is transmitted at the fixed analysis size; original dimensions
        # must match the map above. Intrinsics already use this analysis size.
        route = replace(route, profile=replace(route.profile, width=960, height=540))
        epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
        tracker = AnchoredRouteLocalizer(route, capture_epoch=epoch, episode_id=episode, goal_revision=goal,
                                        clock=self.clock, recovery_candidate_limit=8)
        self.live = dict(id=body['id'], binding=body.copy(), job=job.name, epoch=epoch,
            episode=episode, goal=goal, tracker=tracker, sequence=0, observations=0, deadline=self.clock()+120,
            geometry_sha256=receipt['geometry_sha256'],mode=mode)
        return self.live_status()

    def stop_live(self, job, body, *, mode='live'):
        if type(body) is not dict or set(body) != {'id'} or not isinstance(body['id'], str) or not ID.fullmatch(body['id']):
            raise ValueError('route_session_id')
        self._expire()
        if self.live and self.live['id']==body['id'] and self.live.get('mode','live')!=mode:
            raise ValueError('route_session_mode_changed')
        if body['id'] not in self.retired and len(self.retired) >= 2048:
            raise ValueError('route_session_retirement_quota')
        self.retired[body['id']] = self.clock() + 600  # Fence a delayed start.
        if self.live and self.live['id'] == body['id'] and self.live['job'] == job.name:
            diagnostics=self._finish_diagnostics(self.live)
            self.live = None
            return dict(phase='closed',physicalActions=0,diagnostics=diagnostics)
        return dict(phase='closed', physicalActions=0)

    def start_walk(self, job, body):
        """A separate, explicitly confirmed plan-only session for a foot pilot.

        The browser remains the sole native-input owner. Diagnostic observer
        requests never acquire this planner, even when the map is ready.
        """
        from motor_worker.walk_route import WalkRouteFollower
        from motor_worker.route_tracking import AnchoredRouteLocalizer

        required={'id', 'captureEpoch', 'width', 'height', 'sceneConfirmed', 'footCameraAssumptionConfirmed'}
        if (type(body) is not dict or body.get('footCameraAssumptionConfirmed') is not True
                or not required <= body.keys() or not body.keys() <= required|{'startMode','cameraTracking','cameraControl','diagnosticFrames','clientVersion'}
                or type(body.get('diagnosticFrames',False)) is not bool
                or type(body.get('cameraTracking',False)) is not bool
                or type(body.get('cameraControl','pulse_v1')) is not str
                or body.get('cameraControl','pulse_v1') not in {'pulse_v1','continuous_drag_v1'}
                or 'cameraControl' in body and body.get('cameraTracking') is not True
                or body.get('startMode','beginning') not in {'beginning','recognized_route'}):
            raise ValueError('walk_explicit_confirmation_required')
        if body.get('clientVersion')!='walk_live_v7':
            raise ValueError('Обновите вкладку страницы (Ctrl+R): загружен прежний контур управления. Нужен walk_live_v7.')
        start_mode=body.get('startMode','beginning')
        camera_tracking=body.get('cameraTracking',False)
        camera_control=body.get('cameraControl','pulse_v1')
        request = {key: value for key, value in body.items() if key not in {'footCameraAssumptionConfirmed','startMode','cameraTracking','cameraControl','diagnosticFrames','clientVersion'}}
        self._expire()
        if self.live and self.live['id'] == request['id'] and 'walk' not in self.live:
            raise ValueError('walk_observer_cannot_be_promoted')
        if (self.live and self.live['id']==request['id'] and 'walk' in self.live
                and self.live['walk'].start_mode!=start_mode):
            raise ValueError('walk_start_mode_changed')
        if (self.live and self.live['id']==request['id'] and 'walk' in self.live
                and (self.live['walk'].camera_tracking!=camera_tracking or self.live['walk'].camera_control!=camera_control)):
            raise ValueError('walk_camera_mode_changed')
        if self.live and self.live['id']==request['id'] and bool(self.live.get('frame_archive'))!=body.get('diagnosticFrames',False):
            raise ValueError('walk_diagnostic_mode_changed')
        self.start_live(job, request)
        route=self.live['tracker'].route
        budget=min(600,max(120,math.ceil((route.source_seconds[-1]-route.source_seconds[0])*5+30)))
        self._install_walk(start_mode=start_mode,camera_tracking=camera_tracking,camera_control=camera_control,max_seconds=budget)
        self.live['motion_protocol']='applied_stick_v1'
        if body.get('diagnosticFrames') and not self.live.get('frame_archive'):
            from scripts.pilot.walk_diagnostics import WalkFrameArchive
            self.live['frame_archive']=WalkFrameArchive(job,body['id'],clock=self.clock,
                geometry_sha256=self.live['geometry_sha256'],capture_epoch=body['captureEpoch'])
        return dict(self.live_status(), mode='foot_camera_trace_v1', physicalActions=0, maxSeconds=self.live['walk'].max_seconds,
                    startMode=start_mode,cameraTracking=camera_tracking,cameraControl=camera_control,
                    observationProtocol='jpeg_binary_v1',motionProtocol='applied_stick_v1',clientVersion='walk_live_v7')

    def _install_walk(self, *, start_mode='beginning',camera_tracking=False,camera_control='pulse_v1',max_seconds=60):
        from motor_worker.walk_route import WalkRouteFollower
        from motor_worker.route_tracking import AnchoredRouteLocalizer
        from motor_worker.route_reference_view import reference_rotations
        if 'walk' not in self.live:
            route = self.live['tracker'].route
            # The lower central avatar is not a stationary world landmark.
            # This conservative foot-only query mask does not alter saved map
            # bytes or claim segmentation of dynamic players/traffic.
            profile = replace(route.profile, excluded=(*route.profile.excluded, (.33, .45, .67, 1.)))
            route = replace(route, profile=profile)
            self.live['tracker'] = AnchoredRouteLocalizer(route, capture_epoch=self.live['epoch'],
                episode_id=self.live['episode'], goal_revision=self.live['goal'], clock=self.clock,
                recovery_candidate_limit=8)
            views=reference_rotations(self.folder/self.live['job']/'geometry.json',route,self.live['geometry_sha256'])
            self.live['walk'] = WalkRouteFollower(route, clock=self.clock,start_mode=start_mode,camera_tracking=camera_tracking,
                                                camera_control=camera_control,reference_rotations=views,max_seconds=max_seconds)
            self.live['deadline'] = self.clock()+max_seconds
            self.live['observation_limit']=max_seconds*30
    def start_replay(self,job,body):
        """The real pose/planner path, with a separate recorded-input protocol.

        It can neither be promoted into a live walk nor acquire Android input.
        The recording's clock/route progress never enters localization.
        """
        if type(body) is not dict or set(body)!={'id','captureEpoch','width','height'}:
            raise ValueError('route_replay_binding')
        self.start_live(job,dict(body,sceneConfirmed=True),mode='recorded_replay')
        self._install_walk()
        return dict(self.live_status(),mode='recorded_replay',replayOnly=True,maxSeconds=60)

    def observe(self, job, body, *, mode='live'):
        if (type(body) is not dict or not {'id','captureEpoch','sequence','jpeg'}<=body.keys()
                or not body.keys()<={'id','captureEpoch','sequence','jpeg','motionActive'}
                or type(body['jpeg']) is not str or len(body['jpeg']) > 512*1024):
            raise ValueError('route_observation_not_bound')
        raw=base64.b64decode(body['jpeg'],validate=True)
        return self.observe_jpeg(job,{k:v for k,v in body.items() if k!='jpeg'},raw,mode=mode)

    def observe_jpeg(self, job, body, raw, *, mode='live'):
        import cv2 as cv
        import numpy as np
        from PIL import Image

        from motor_worker.policy import PolicyFrame
        from motor_worker.route_localization import PNP_VERIFICATION_POLICY, COARSE_SEARCH_POLICY

        self._expire()
        if (type(body) is not dict or not {'id', 'captureEpoch', 'sequence'}<=body.keys()
                or not body.keys()<={'id','captureEpoch','sequence','motionActive'}
                or 'motionActive' in body and type(body['motionActive']) is not bool
                or self.live is None or self.live['id'] != body['id'] or self.live['job'] != job.name
                or self.live.get('mode','live')!=mode
                or body['captureEpoch'] != self.live['binding']['captureEpoch']
                or type(body['sequence']) is not int or body['sequence'] <= self.live['sequence']
                or body['sequence'] > 1000000):
            raise ValueError('route_observation_not_bound')
        if self.live.get('motion_protocol')=='applied_stick_v1' and 'motionActive' not in body:
            raise ValueError('walk_motion_feedback_required')
        if type(raw) is not bytes or not 100 <= len(raw) <= 384*1024:
            raise ValueError('route_jpeg_quota')
        with Image.open(io.BytesIO(raw)) as header:
            if header.format != 'JPEG' or header.size != (960, 540):
                raise ValueError('route_jpeg_geometry')
        # Header validated before allocating decoded image; never write pixels.
        image = cv.imdecode(np.frombuffer(raw, np.uint8), cv.IMREAD_COLOR)
        if image is None or image.shape != (540, 960, 3):
            raise ValueError('route_jpeg_decode')
        rgb = cv.cvtColor(image, cv.COLOR_BGR2RGB).tobytes()
        now = self.clock()
        session = self.live
        session['sequence'] = body['sequence']
        session['observations'] += 1
        if session['observations'] > session.get('observation_limit',1200):
            self.retired[session['id']] = self.clock() + 600
            self.live = None
            raise ValueError('route_live_observation_quota')
        frame = PolicyFrame(session['epoch'], body['sequence'], now, 960, 540, rgb)
        pose = session['tracker'].observe(frame, episode_id=session['episode'], goal_revision=session['goal'], scene='active')
        elapsed = (self.clock()-now)*1000
        values = asdict(pose)
        result = dict(id=session['id'], sequence=body['sequence'], jpegSha256=hashlib.sha256(raw).hexdigest(),
            captureEpoch=body['captureEpoch'], pose=values, computeMs=elapsed, geometrySha256=session['geometry_sha256'],
            method=session['tracker'].last_diagnostic.get('method', 'not_attempted'),
            verificationPolicy=PNP_VERIFICATION_POLICY,
            coarseSearchPolicy=COARSE_SEARCH_POLICY,
            physicalActions=0, framesArchived=0, executionQualified=False, groundRoute=False,
            viewCompatibility='same_aspect_assumed_same_fov',
            fullAndroidLatencyKnown=False, sceneIsOperatorAssumption=True)
        result['replayOnly']=mode=='recorded_replay'
        result['referenceTicks90k']=None
        if pose.state=='localized' and pose.segment is not None:
            trace=session['tracker'].route.camera_trace;index=min(pose.segment,len(trace)-2)
            candidates=(index,index+1)
            nearest=min(candidates,key=lambda i:sum((a-b)**2 for a,b in zip(trace[i],pose.center)))
            result['referenceTicks90k']=round(session['tracker'].route.source_seconds[nearest]*90000)
        if 'walk' in session:
            result['walk'] = session['walk'].observe(pose,motion_active=body.get('motionActive'))
            result['walk']['motionActive']=body.get('motionActive')
            result['walk']['motionSeconds']=session['walk'].motion_seconds
        if session.get('frame_archive'):
            session['frame_archive'].offer(raw,sequence=body['sequence'],pose=pose,plan=result.get('walk'),
                method=result['method'],compute_ms=elapsed)
        return result
