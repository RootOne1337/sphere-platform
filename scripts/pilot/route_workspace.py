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


def resource_checkpoint(folder):
    if (folder/'CANCEL').exists():
        raise RuntimeError('cancelled')
    snapshot = collect(ROOT)
    findings = evaluate(snapshot, min_ram_gib=12)
    if findings:
        if folder.is_dir():
            write_json(folder/'resource-refusal.json', dict(snapshot=snapshot, findings=findings))
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
            return dict(phase='not_prepared', executionQualified=False)
        result = dict(checked_json(folder/'state.json'), id=folder.name, executionQualified=False)
        if result['phase'] == 'ready':
            receipt = checked_json(folder/'receipt.json')
            if (receipt.get('geometry_sha256') != digest_file(job/'geometry.json')
                    or receipt.get('source_capture_sha256') != digest_file(job/'input/manifest.json')):
                return dict(phase='rejected', error='route_source_changed', executionQualified=False)
            support = receipt.get('map_support', {})
            coverage = receipt.get('source_coverage', {})
            if (support.get('all_reference_neighborhoods_supported') is not True
                    or support.get('all_reference_intervals_observed') is not True
                    or coverage.get('endpoints_observed') is not True):
                return dict(phase='rejected', error='route_map_has_unobserved_sections', executionQualified=False)
            from motor_worker.route_localization import pipeline_id
            if receipt.get('pipeline_sha256') != pipeline_id():
                return dict(phase='rejected', error='route_feature_runtime_mismatch', executionQualified=False)
            result['summary'] = {key: receipt[key] for key in ('cameras', 'landmarks', 'map_support', 'camera_trace_only')}
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
        if self.preparing(job) or self.live is not None:
            raise ValueError('route_workspace_busy')
        if len(list((job/'navigation').glob('*/intent.json'))) >= 3:
            raise ValueError('route_preparation_attempt_quota')
        resource_checkpoint(job)
        folder.mkdir(parents=True)
        write_json(folder/'intent.json', dict(id=identity, scope='READ_ONLY_ROUTE_ASSETS', physicalActions=0))
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
        threading.Thread(target=self._monitor, args=(folder, process), daemon=True).start()
        return self.status(job)

    def _monitor(self, folder, process):
        deadline = time.monotonic()+330
        while process.poll() is None:
            time.sleep(3)
            try:
                resource_checkpoint(folder)
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
            self.retired[self.live['id']] = now + 600
            self.live = None

    def live_status(self):
        self._expire()
        if self.live is None:
            return dict(phase='idle', physicalActions=0)
        return dict(phase='observing', id=self.live['id'], job=self.live['job'],
                    observations=self.live['observations'], secondsRemaining=max(0, self.live['deadline']-self.clock()),
                    physicalActions=0)

    def start_live(self, job, body):
        from motor_worker.route_localization import SparseRoute
        from motor_worker.route_tracking import AnchoredRouteLocalizer

        if (type(body) is not dict or set(body) != {'id', 'captureEpoch', 'width', 'height', 'sceneConfirmed'}
                or not isinstance(body['id'], str) or not ID.fullmatch(body['id'])
                or not isinstance(body['captureEpoch'], str)
                or not re.fullmatch(r'[0-9a-f-]{16,64}', body['captureEpoch'])
                or body['sceneConfirmed'] is not True):
            raise ValueError('route_live_confirmation_or_binding')
        self._expire()
        if self.live is not None:
            if self.live['id'] == body['id'] and self.live['job'] == job.name and self.live['binding'] == body:
                return self.live_status()
            raise ValueError('one_live_route_observer_only')
        if body['id'] in self.retired or len(self.retired) >= 2048:
            raise ValueError('route_session_retired_or_quota')
        if self.status(job)['phase'] != 'ready':
            raise ValueError('route_assets_not_ready')
        resource_checkpoint(job)
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
        tracker = AnchoredRouteLocalizer(route, capture_epoch=epoch, episode_id=episode, goal_revision=goal, clock=self.clock)
        self.live = dict(id=body['id'], binding=body.copy(), job=job.name, epoch=epoch,
            episode=episode, goal=goal, tracker=tracker, sequence=0, observations=0, deadline=self.clock()+120)
        return self.live_status()

    def stop_live(self, job, body):
        if type(body) is not dict or set(body) != {'id'} or not isinstance(body['id'], str) or not ID.fullmatch(body['id']):
            raise ValueError('route_session_id')
        self._expire()
        if body['id'] not in self.retired and len(self.retired) >= 2048:
            raise ValueError('route_session_retirement_quota')
        self.retired[body['id']] = self.clock() + 600  # Fence a delayed start.
        if self.live and self.live['id'] == body['id'] and self.live['job'] == job.name:
            self.live = None
        return dict(phase='closed', physicalActions=0)

    def start_walk(self, job, body):
        """A separate, explicitly confirmed plan-only session for a foot pilot.

        The browser remains the sole native-input owner. Diagnostic observer
        requests never acquire this planner, even when the map is ready.
        """
        from motor_worker.walk_route import WalkRouteFollower
        from motor_worker.route_tracking import AnchoredRouteLocalizer

        if (type(body) is not dict or body.get('footCameraAssumptionConfirmed') is not True
                or set(body) != {'id', 'captureEpoch', 'width', 'height', 'sceneConfirmed',
                                 'footCameraAssumptionConfirmed'}):
            raise ValueError('walk_explicit_confirmation_required')
        request = {key: value for key, value in body.items() if key != 'footCameraAssumptionConfirmed'}
        self._expire()
        if self.live and self.live['id'] == request['id'] and 'walk' not in self.live:
            raise ValueError('walk_observer_cannot_be_promoted')
        self.start_live(job, request)
        if 'walk' not in self.live:
            route = self.live['tracker'].route
            # The lower central avatar is not a stationary world landmark.
            # This conservative foot-only query mask does not alter saved map
            # bytes or claim segmentation of dynamic players/traffic.
            profile = replace(route.profile, excluded=(*route.profile.excluded, (.33, .45, .67, 1.)))
            route = replace(route, profile=profile)
            self.live['tracker'] = AnchoredRouteLocalizer(route, capture_epoch=self.live['epoch'],
                episode_id=self.live['episode'], goal_revision=self.live['goal'], clock=self.clock)
            self.live['walk'] = WalkRouteFollower(route, clock=self.clock)
            self.live['deadline'] = min(self.live['deadline'], self.clock()+60)
        return dict(self.live_status(), mode='foot_camera_trace_v1', physicalActions=0, maxSeconds=60)

    def observe(self, job, body):
        import cv2 as cv
        import numpy as np
        from PIL import Image

        from motor_worker.policy import PolicyFrame
        from motor_worker.route_localization import PNP_VERIFICATION_POLICY

        self._expire()
        if (type(body) is not dict or set(body) != {'id', 'captureEpoch', 'sequence', 'jpeg'}
                or self.live is None or self.live['id'] != body['id'] or self.live['job'] != job.name
                or body['captureEpoch'] != self.live['binding']['captureEpoch']
                or type(body['sequence']) is not int or body['sequence'] <= self.live['sequence']
                or body['sequence'] > 1000000 or type(body['jpeg']) is not str or len(body['jpeg']) > 512*1024):
            raise ValueError('route_observation_not_bound')
        raw = base64.b64decode(body['jpeg'], validate=True)
        if not 100 <= len(raw) <= 384*1024:
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
        if session['observations'] > 1200:
            self.retired[session['id']] = self.clock() + 600
            self.live = None
            raise ValueError('route_live_observation_quota')
        frame = PolicyFrame(session['epoch'], body['sequence'], now, 960, 540, rgb)
        pose = session['tracker'].observe(frame, episode_id=session['episode'], goal_revision=session['goal'], scene='active')
        elapsed = (self.clock()-now)*1000
        values = asdict(pose)
        result = dict(id=session['id'], sequence=body['sequence'], jpegSha256=hashlib.sha256(raw).hexdigest(),
            captureEpoch=body['captureEpoch'], pose=values, computeMs=elapsed,
            method=session['tracker'].last_diagnostic.get('method', 'not_attempted'),
            verificationPolicy=PNP_VERIFICATION_POLICY,
            physicalActions=0, framesArchived=0, executionQualified=False, groundRoute=False,
            viewCompatibility='same_aspect_assumed_same_fov',
            fullAndroidLatencyKnown=False, sceneIsOperatorAssumption=True)
        if 'walk' in session:
            result['walk'] = session['walk'].observe(pose)
        return result
