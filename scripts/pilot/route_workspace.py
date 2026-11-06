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
from scripts.pilot.route_owned_process import spawn_owned

ROOT = Path(__file__).resolve().parents[2]
ID = re.compile(r'^[0-9a-f]{32}$')
TERMINAL = {'ready', 'failed', 'rejected', 'cancelled', 'awaiting_qualification'}


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
                    maxFrameBytes=384*1024, minDiskGiB=1., modelLoaded=False, maxCommitPercent=90)
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


def resource_checkpoint(folder, *, profile=None, snapshot=None):
    """Evaluate fresh counters; preparation may supply its task-owned snapshot.

    Other callers retain the existing fresh full collection. A supplied snapshot
    never changes the profile, cancellation, volume or absolute commit gates.
    """
    if (folder/'CANCEL').exists():
        raise RuntimeError('cancelled')
    snapshot = collect(ROOT) if snapshot is None else snapshot
    if type(snapshot) is not dict:
        raise ValueError('route_resource_snapshot')
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
    commit_max=85 if profile is None else profile.get('maxCommitPercent',85)
    if (type(commit_max) not in {int,float} or not 0<commit_max<=90
            or commit_max!=85 and (profile is None or profile.get('kind')!='route_live')):
        raise ValueError('route_resource_profile')
    findings = evaluate(snapshot, min_ram_gib=minimum, min_disk_gib=disk_minimum,max_commit_percent=commit_max)
    if (snapshot.get('system')=='Windows' and type(snapshot.get('committedBytes'))is int
            and type(snapshot.get('commitLimitBytes'))is int
            and snapshot['commitLimitBytes']-snapshot['committedBytes']<minimum*1024**3
            and 'commit_headroom_low'not in findings):findings.append('commit_headroom_low')
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
        self.processes = {}
        for state in folder.glob('*/navigation/*/state.json'):
            if checked_json(state)['phase'] not in TERMINAL:
                (state.parent/'CANCEL').touch(exist_ok=True)
                interrupted = dict(phase='failed', error='route_service_restarted')
                write_json(state.parent/'service-interrupted.json', interrupted)
                write_json(state, interrupted)

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
        from scripts.pilot.route_reconstruction_recipe import admission_ladder
        # The gate and its display use one fresh hash per path in this request.
        # Do not repeatedly hash a multi-megabyte geometry for the same poll,
        # and do not retain hashes across polls where the source may change.
        hashes = {}
        def source_digest(path):
            if path not in hashes:
                hashes[path] = digest_file(path)
            return hashes[path]
        result = self._status(job, digest=source_digest)
        result['admission'] = admission_ladder(job, result, read_json=checked_json, digest=source_digest)
        from scripts.pilot.route_preparation_source import preparation_sources
        result['preparationSources'] = preparation_sources(job, digest=source_digest)
        if result.get('source', {}).get('alternativeId') is not None:
            result['admission']['geometry'] = dict(status='accepted', reason='alternative_native_geometry_gate')
        return result

    def _status(self, job, *, digest=digest_file):
        folder = self.current(job)
        if folder is None:
            return dict(phase='not_prepared', executionQualified=False,
                        resourceProfile=route_resource_profile(job))
        result = dict(self._attempt_state(folder), id=folder.name, executionQualified=False,
                      resourceProfile=route_resource_profile(job))
        from scripts.pilot.route_preparation_source import attempt_source, public_source
        try:
            selected = attempt_source(job, folder, digest=digest)
            result['source'] = public_source(selected, digest=digest)
        except (OSError, ValueError, TypeError, KeyError):
            return dict(result, phase='rejected', error='route_preparation_source_changed')
        if result['phase'] == 'ready' and not (folder/'receipt.json').is_file():
            return dict(result, phase='rejected', error='route_receipt_missing')
        if result['phase'] in {'ready', 'rejected', 'awaiting_qualification'} and (folder/'receipt.json').exists():
            receipt = checked_json(folder/'receipt.json')
            if (receipt.get('geometry_sha256') != digest(selected['geometry_path'])
                    or receipt.get('source_capture_sha256') != digest(job/'input/manifest.json')):
                return dict(result, phase='rejected', error='route_source_changed')
            if selected['binding'] is not None and receipt.get('source_binding') != selected['binding']:
                return dict(result, phase='rejected', error='route_preparation_source_changed')
            support = receipt.get('map_support') or {}
            coverage = receipt.get('source_coverage') or {}
            # Keep the measured cause available even for a rejected result.
            # A new preflight failure does not erase this previous attempt.
            result['summary'] = {key: receipt.get(key) for key in
                ('cameras', 'landmarks', 'first_seconds', 'last_seconds', 'source_coverage',
                 'map_support', 'camera_trace_only', 'pipeline_sha256')}
            if (support.get('all_reference_neighborhoods_supported') is not True
                    or support.get('all_reference_intervals_observed') is not True
                    or coverage.get('endpoints_observed') is not True):
                return dict(result, phase='rejected', error='route_map_has_unobserved_sections')
            from motor_worker.route_localization import native_reference_pipeline_id, pipeline_id
            if selected['binding'] is not None:
                from scripts.pilot.route_reference_lk_export import (
                    validate_reference_lk_qualification, validate_reference_lk_receipt,
                )
                try:
                    validate_reference_lk_receipt(receipt, folder,
                        source_capture_sha256=digest(job/'input/manifest.json'),
                        source_index_sha256=digest(selected['index_path']),
                        geometry_sha256=selected['binding']['geometry_sha256'],
                        model_sha256=selected['binding']['model_sha256'])
                except (OSError, ValueError, TypeError, KeyError):
                    return dict(result, phase='rejected', error='route_reference_lk_invalid')
                try:
                    validate_reference_lk_qualification(receipt, folder, source_binding=selected['binding'])
                except (OSError, ValueError, TypeError, KeyError):
                    return dict(result, phase='awaiting_qualification', error='route_reference_lk_unqualified')
                return dict(result, phase='ready', error=None, controlledExperimentalTestOnly=True,
                            vehicleVisualTempoAvailable=self._visual_tempo_source(job))
            if receipt.get('pipeline_sha256') == native_reference_pipeline_id():
                from scripts.pilot.route_native_landmarks import validate_reference_receipt
                try:
                    validate_reference_receipt(receipt, folder, source_sha256=digest(job/'input/manifest.json'),
                                               source_index_sha256=digest(job/'prepared/reconstruction-input.json'))
                except (OSError, ValueError, TypeError, KeyError):
                    return dict(result, phase='rejected', error='route_native_reference_invalid')
                # Exact measured binding is not runtime localization evidence.
                # This family is offline-only until a reviewed qualification
                # contract exists; map support/point count cannot promote it.
                return dict(result, phase='rejected', error='route_native_reference_unqualified')
            elif receipt.get('pipeline_sha256') != pipeline_id() or 'native_reference' in receipt:
                return dict(result, phase='rejected', error='route_feature_runtime_mismatch')
        return result

    def preparing(self, job):
        return (job.name in self.processes
                or self.status(job)['phase'] not in TERMINAL | {'not_prepared'})

    @staticmethod
    def _attempt_state(folder):
        fence = folder/'service-interrupted.json'
        return checked_json(fence if fence.is_file() else folder/'state.json')

    def prepare(self, job, body):
        self._expire()
        self.current(job)  # Validate the fixed root before creating any directory.
        identity = body.get('id') if type(body) is dict else None
        if (not isinstance(identity, str) or not ID.fullmatch(identity)
                or set(body) not in ({'id'}, {'id', 'alternativeId'})):
            raise ValueError('route_preparation_intent')
        alternative_id = body.get('alternativeId')
        if 'alternativeId' in body:
            from scripts.pilot.alternative_geometry import ID as ALTERNATIVE_ID
            if not isinstance(alternative_id, str) or not ALTERNATIVE_ID.fullmatch(alternative_id):
                raise ValueError('route_alternative_id')
        folder = job/'navigation'/identity
        if folder.exists():
            # Repeated intent reads its own outcome; never repeat a lost start.
            intent = checked_json(folder/'intent.json') if (folder/'intent.json').exists() else {}
            if intent.get('alternativeId') != alternative_id:
                raise ValueError('route_preparation_intent_source_changed')
            return dict(self._attempt_state(folder), id=identity, executionQualified=False)
        current = self.status(job)
        if (current.get('error') == 'route_map_has_unobserved_sections'
                and current.get('source', {}).get('alternativeId') == alternative_id):
            summary = current.get('summary', {})
            if ((summary.get('source_coverage') or {}).get('endpoints_observed') is False
                    or (summary.get('map_support') or {}).get('all_reference_intervals_observed') is False):
                # Exporting identical poses cannot fill a missing time interval.
                # Preserve the old attempt and do not spend another intent.
                raise ValueError('route_camera_recovery_required')
        if self.preparing(job) or self.live is not None:
            raise ValueError('route_workspace_busy')
        intents = list((job/'navigation').glob('*/intent.json'))
        source_attempts = sum(checked_json(path).get('alternativeId') == alternative_id for path in intents)
        if ((alternative_id is None and len(intents) >= 3)
                or (alternative_id is not None and (source_attempts >= 3 or len(intents) >= 16))):
            raise ValueError('route_preparation_attempt_quota')
        profile = route_resource_profile(job)
        source_intent = {}
        if alternative_id is not None:
            from scripts.pilot.route_preparation_source import cancel_marker, resolve_alternative_source
            selected = resolve_alternative_source(job, alternative_id)
            marker = cancel_marker(job/'CANCEL')
            source_intent = dict(alternativeId=alternative_id, sourceBinding=selected['binding'],
                                cancellationPolicy=dict(parentCancelAtIntent=marker))
            resource_checkpoint(folder, profile=profile)
            if cancel_marker(job/'CANCEL') != marker:
                raise RuntimeError('cancelled')
        else:
            resource_checkpoint(job, profile=profile)
        folder.mkdir(parents=True)
        process = None
        self.processes[job.name] = None
        try:
            write_json(folder/'intent.json', dict(id=identity, scope='READ_ONLY_ROUTE_ASSETS', physicalActions=0,
                                               resourceProfile=profile, **source_intent))
            write_json(folder/'state.json', dict(phase='preparing'))
            write_json(job/'navigation/active.json', dict(id=identity))
            with (folder/'worker.private.log').open('xb') as log:
                process = spawn_owned([str(self.python), '-m', 'scripts.pilot.prepare_route_workspace',
                    '--job', str(job), '--attempt', identity], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if hasattr(process, 'ownership'):
                write_json(folder/'worker-ownership.json', process.ownership)
            self.processes[job.name] = process
            threading.Thread(target=self._monitor, args=(folder, process, profile), daemon=True).start()
        except Exception:
            try:
                if process is not None and process.poll() is None:
                    self._stop_process(process)
            finally:
                if process is not None and hasattr(process, 'close'):
                    process.close()
                self.processes.pop(job.name, None)
                from scripts.pilot.route_preparation_source import attempt_cancelled
                write_json(folder/'state.json', dict(phase='cancelled' if attempt_cancelled(job, folder) else 'failed',
                                                    error='route_start_not_confirmed'))
            raise
        return self.status(job)

    def _monitor(self, folder, process, profile=None):
        try:
            self._monitor_process(folder, process, profile)
        except Exception:
            try:
                if process.poll() is None:
                    self._stop_process(process)
            finally:
                from scripts.pilot.route_preparation_source import attempt_cancelled
                write_json(folder/'state.json', dict(phase='cancelled' if attempt_cancelled(folder.parent.parent, folder) else 'failed',
                                                    error='route_monitor_failed'))
        finally:
            if hasattr(process, 'close'):
                process.close()
            self.processes.pop(folder.parent.parent.name, None)

    @staticmethod
    def _stop_process(process):
        if hasattr(process, 'stop'):
            process.stop(timeout=10)
        else:
            process.kill()
            process.wait(10)

    def _monitor_process(self, folder, process, profile=None):
        from scripts.pilot.route_resource_monitor import TaskResourceMonitor

        # The export worker already owns its own volume proof. Its supervisor
        # must also scope recurring health checks to this process lifetime,
        # rather than launch a synchronous PowerShell discovery every 3 s.
        # Native RAM/commit/disk remain fresh on every sample; no proof is
        # shared across workers, and close reaps a pending owned probe.
        with TaskResourceMonitor(ROOT) as monitor:
            self._monitor_owned_process(folder, process, profile, monitor)

    def _monitor_owned_process(self, folder, process, profile, monitor):
        from scripts.pilot.route_preparation_source import attempt_cancelled
        deadline = time.monotonic()+330
        while process.poll() is None:
            time.sleep(3)
            # A child may have finished during the supervisor interval. Do
            # not spend another health probe or replace its terminal result
            # with a refusal caused by unrelated later host pressure.
            if process.poll() is not None:
                break
            try:
                if attempt_cancelled(folder.parent.parent, folder):
                    raise RuntimeError('cancelled')
                resource_checkpoint(folder, profile=profile, snapshot=monitor.sample())
                if time.monotonic() > deadline:
                    raise RuntimeError('route_preparation_timeout')
                if (folder/'worker.private.log').stat().st_size > 8*1024**2:
                    raise RuntimeError('route_log_quota')
            except RuntimeError as exc:
                self._stop_process(process)
                write_json(folder/'state.json', dict(phase='cancelled' if str(exc) == 'cancelled' else 'failed', error=str(exc)))
                return
        if attempt_cancelled(folder.parent.parent, folder):
            write_json(folder/'state.json', dict(phase='cancelled', error='cancelled'))
            return
        if checked_json(folder/'state.json')['phase'] not in TERMINAL:
            write_json(folder/'state.json', dict(phase='failed', error='route_export_not_confirmed'))

    def _expire(self):
        now = self.clock()
        self.retired = {identity: deadline for identity, deadline in self.retired.items() if deadline > now}
        if self.live and self.clock() >= self.live['deadline']:
            self._retire_live(self.live, now)

    def _retire_live(self, session, now):
        # Fence the session before optional, bounded archive I/O. Browser
        # input ownership remains independent of the local diagnostic write.
        self.retired[session['id']] = now + 600
        self.live = None
        try:
            self._close_runtime(session)
        finally:
            diagnostics = self._finish_diagnostics(session)
        return diagnostics

    @staticmethod
    def _close_runtime(session):
        metadata = session.get('metadata_ring')
        if metadata is not None:
            try:
                metadata.close()
            except Exception:
                pass  # Optional diagnostics cannot change contact release.
        tracker = session.get('tracker')
        route = getattr(tracker, 'route', None)
        for resource in (tracker, route):
            close = getattr(resource, 'close', None)
            if close is not None:
                close()

    @staticmethod
    def _runtime_source_stamp(paths):
        # Hashes are verified by source/receipt/load admission. A live session
        # then owns immutable bytes; a cheap file-identity fence catches any
        # later replacement/touch without hashing its gray cache each frame.
        values = []
        for path in paths:
            if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
                raise ValueError('route_source_changed')
            stat = path.stat()
            values.append((stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        return tuple(values)

    def _validate_live_source(self, session):
        paths = session.get('source_paths')
        if paths is not None:
            try:
                unchanged = self._runtime_source_stamp(paths) == session['source_stamp']
            except (OSError, ValueError):
                unchanged = False
            if not unchanged:
                self._retire_live(session, self.clock())
                raise ValueError('route_source_changed')

    @staticmethod
    def _finish_diagnostics(session):
        archive = session.get('frame_archive')
        if archive is None:
            return None
        try:
            return archive.finish()
        except Exception:
            return dict(state='unconfirmed', frames=0, bytes=0)

    def live_status(self):
        self._expire()
        if self.live is None:
            return dict(phase='idle', physicalActions=0)
        return dict(phase='observing', id=self.live['id'], job=self.live['job'],
                    observations=self.live['observations'], secondsRemaining=max(0, self.live['deadline']-self.clock()),
                    confirmationPolicy=getattr(self.live['tracker'], 'confirmation_policy', None),
                    confirmationRuntimeSha256=getattr(self.live['tracker'], 'confirmation_runtime_sha256', None),
                    descriptorRecoveryPolicy=self.live.get('descriptor_recovery_policy'),
                    physicalActions=0)

    def start_live(self, job, body, *, mode='live', observation_only=True):
        import cv2 as cv
        from motor_worker.route_localization import SparseRoute
        from motor_worker.route_tracking import AnchoredRouteLocalizer

        required = {'id', 'captureEpoch', 'width', 'height', 'sceneConfirmed'}
        if (mode not in {'live','recorded_replay'} or type(body) is not dict
                or not required <= body.keys() or not body.keys() <= required | {'expectedSource'}
                or not isinstance(body['id'], str) or not ID.fullmatch(body['id'])
                or not isinstance(body['captureEpoch'], str)
                or not re.fullmatch(r'[0-9a-f-]{16,64}', body['captureEpoch'])
                or body['sceneConfirmed'] is not True):
            raise ValueError('route_live_confirmation_or_binding')
        self._expire()
        from scripts.pilot.route_preparation_source import attempt_cancelled, attempt_source, public_source
        folder = self.current(job)
        selected = attempt_source(job, folder) if folder is not None else None
        expected_source = body.get('expectedSource')
        if expected_source is not None:
            if (not isinstance(expected_source, dict)
                    or set(expected_source) != {'alternativeId', 'geometry_sha256', 'runtime_family'}
                    or selected is None or expected_source != public_source(selected)):
                raise ValueError('route_start_source_changed')
        elif selected is not None and selected['binding'] is not None:
            raise ValueError('route_start_source_confirmation_required')
        if self.live is not None:
            if (self.live['id'] == body['id'] and self.live['job'] == job.name and self.live['binding'] == body
                    and self.live.get('mode','live')==mode):
                self._validate_live_source(self.live)
                return self.live_status()
            raise ValueError('one_live_route_observer_only')
        if body['id'] in self.retired or len(self.retired) >= 2048:
            raise ValueError('route_session_retired_or_quota')
        if self.status(job)['phase'] != 'ready':
            raise ValueError('route_assets_not_ready')
        folder = self.current(job)
        if selected != attempt_source(job, folder):
            raise ValueError('route_start_source_changed')
        reference_lk = selected['binding'] is not None
        if reference_lk and attempt_cancelled(job, folder):
            raise RuntimeError('cancelled')
        resource_checkpoint(folder if reference_lk else job, profile=route_resource_profile(job, 'live'))
        # One observation is processed at a time. Bound native parallelism while
        # leaving headroom inside the 250 ms receiver-age budget for SIFT/PnP.
        cv.setNumThreads(2 if reference_lk else 4)
        receipt = checked_json(folder/'receipt.json')
        if reference_lk:
            from motor_worker.route_reference_lk import ReferenceLKRoute
            from motor_worker.route_confirmation import ReferenceLKConfirmationLocalizer
            route = ReferenceLKRoute.load(folder/'route.json', sha256=receipt['sha256'])
        else:
            route = SparseRoute.load(folder/'route.json', sha256=receipt['sha256'])
        if (type(body['width']) is not int or type(body['height']) is not int
                or not 128 <= body['width'] <= 8192 or not 128 <= body['height'] <= 8192
                or body['width']*body['height'] > 8*1024**2
                or body['width']*route.profile.height != body['height']*route.profile.width):
            if reference_lk:
                route.close()
            raise ValueError('route_live_geometry_changed')
        # JPEG is transmitted at the fixed analysis size; original dimensions
        # must match the map above. Intrinsics already use this analysis size.
        if not reference_lk:
            route = replace(route, profile=replace(route.profile, width=960, height=540))
        epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
        recovery_paths, recovery_stamp, recovery_policy = (), None, None
        try:
            options = dict(capture_epoch=epoch, episode_id=episode, goal_revision=goal, clock=self.clock)
            if reference_lk:
                sidecar = None
                if mode == 'live' and observation_only:
                    from scripts.pilot.route_descriptor_attachment import load_descriptor_recovery
                    sidecar, recovery_paths, recovery_stamp = load_descriptor_recovery(
                        folder, receipt, stamp=self._runtime_source_stamp)
                if sidecar is None:
                    tracker = ReferenceLKConfirmationLocalizer(route, **options)
                else:
                    from motor_worker.route_descriptor_recovery import (
                        DESCRIPTOR_RECOVERY_POLICY, ReferenceLKRecoveryLocalizer,
                    )
                    tracker = ReferenceLKRecoveryLocalizer(route, sidecar=sidecar, **options)
                    recovery_policy = DESCRIPTOR_RECOVERY_POLICY
            else:
                tracker = AnchoredRouteLocalizer(route, recovery_candidate_limit=8, **options)
        except BaseException:
            if reference_lk:
                route.close()
            raise
        source_paths = None
        try:
            if reference_lk:
                from scripts.pilot.route_preparation_source import MODEL_FILES
                if attempt_source(job, folder) != selected:
                    raise ValueError('route_source_changed')
                source_paths = (selected['geometry_path'], job/'input/manifest.json',
                    job/'prepared/reconstruction-input.json', job/'navigation/active.json',
                    folder/'intent.json', folder/'receipt.json',
                    folder/'route.json', folder/'reference-lk.npz', folder/'controlled-test-qualification.json',
                    folder/'reference-lk-positive.json', folder/'reference-lk-transport.json',
                    folder/'reference-lk-negative.json', selected['model_path'].parent/'source.json',
                    selected['model_path'].parent/'assessment.json', selected['model_path'].parent/'producer-proof.json',
                    *(selected['model_path']/name for name in sorted(MODEL_FILES)),
                    ROOT/'motor_worker/route_confirmation.py', ROOT/'motor_worker/vehicle_route.py', *recovery_paths)
                if selected['index_path'] != job/'prepared/reconstruction-input.json':
                    source_paths += (selected['index_path'],
                                     selected['index_path'].parent.parent/'input/manifest.json')
            source_stamp = self._runtime_source_stamp(source_paths) if source_paths else None
            if recovery_paths and self._runtime_source_stamp(recovery_paths) != recovery_stamp:
                raise ValueError('route_descriptor_recovery_changed')
        except BaseException:
            if reference_lk:
                tracker.close()
                route.close()
            raise
        self.live = dict(id=body['id'], binding=body.copy(), job=job.name, epoch=epoch,
            episode=episode, goal=goal, tracker=tracker, sequence=0, observations=0, deadline=self.clock()+120,
            geometry_sha256=receipt['geometry_sha256'],mode=mode,
            geometry_path=selected['geometry_path'], source=public_source(selected),
            source_binding=selected['binding'],
            runtime_family='reference_lk' if reference_lk else 'legacy_sparse', preparation_folder=folder,
            source_paths=source_paths, source_stamp=source_stamp, descriptor_recovery_policy=recovery_policy)
        if reference_lk:
            try:
                from scripts.pilot.walk_diagnostics import RuntimeMetadataRing
                self.live['metadata_ring'] = RuntimeMetadataRing(job, clock=self.clock)
            except Exception:
                pass  # A failed optional logger never blocks a valid test.
        return self.live_status()

    def stop_live(self, job, body, *, mode='live'):
        if type(body) is not dict or set(body) != {'id'} or not isinstance(body['id'], str) or not ID.fullmatch(body['id']):
            raise ValueError('route_session_id')
        self._expire()
        if self.live and self.live['id']==body['id'] and self.live.get('mode','live')!=mode:
            raise ValueError('route_session_mode_changed')
        if body['id'] not in self.retired and len(self.retired) >= 2048:
            raise ValueError('route_session_retirement_quota')
        now = self.clock()
        if self.live and self.live['id'] == body['id'] and self.live['job'] == job.name:
            diagnostics = self._retire_live(self.live, now)
            return dict(phase='closed',physicalActions=0,diagnostics=diagnostics)
        self.retired[body['id']] = now + 600  # Fence a delayed start.
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
                or not required <= body.keys() or not body.keys() <= required|{'startMode','cameraTracking','cameraControl','diagnosticFrames','clientVersion','expectedSource'}
                or type(body.get('diagnosticFrames',False)) is not bool
                or type(body.get('cameraTracking',False)) is not bool
                or type(body.get('cameraControl','pulse_v1')) is not str
                or body.get('cameraControl','pulse_v1') not in {'pulse_v1','continuous_drag_v1'}
                or 'cameraControl' in body and body.get('cameraTracking') is not True
                or body.get('startMode','beginning') not in {'beginning','recognized_route'}):
            raise ValueError('walk_explicit_confirmation_required')
        if body.get('clientVersion')!='walk_live_v8':
            raise ValueError('Обновите вкладку страницы (Ctrl+R): загружен прежний контур управления. Нужен walk_live_v8.')
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
        self.start_live(job, request, observation_only=False)
        try:
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
                        observationProtocol='jpeg_binary_v1',motionProtocol='applied_stick_v1',clientVersion='walk_live_v8')
        except BaseException:
            self._retire_live(self.live, self.clock())
            raise

    def _install_walk(self, *, start_mode='beginning',camera_tracking=False,camera_control='pulse_v1',max_seconds=60):
        from motor_worker.walk_route import WalkRouteFollower
        from motor_worker.route_tracking import AnchoredRouteLocalizer
        from motor_worker.route_reference_view import reference_rotations
        if 'walk' not in self.live:
            route = self.live['tracker'].route
            # The lower central avatar is not a stationary world landmark.
            # This conservative foot-only query mask does not alter saved map
            # bytes or claim segmentation of dynamic players/traffic.
            if self.live.get('runtime_family') != 'reference_lk':
                profile = replace(route.profile, excluded=(*route.profile.excluded, (.33, .45, .67, 1.)))
                route = replace(route, profile=profile)
                self.live['tracker'] = AnchoredRouteLocalizer(route, capture_epoch=self.live['epoch'],
                    episode_id=self.live['episode'], goal_revision=self.live['goal'], clock=self.clock,
                    recovery_candidate_limit=8)
            views=reference_rotations(self.live.get('geometry_path', self.folder/self.live['job']/'geometry.json'),
                                      route,self.live['geometry_sha256'])
            self.live['walk'] = WalkRouteFollower(route, clock=self.clock,start_mode=start_mode,camera_tracking=camera_tracking,
                                                camera_control=camera_control,reference_rotations=views,max_seconds=max_seconds)
            self.live['deadline'] = self.clock()+max_seconds
            self.live['observation_limit']=max_seconds*30

    @staticmethod
    def _visual_tempo_source(job, *, manifest=None):
        if manifest is None:
            manifest = checked_json(job/'input/manifest.json')
        config = manifest.get('config') if isinstance(manifest, dict) else None
        profile = config.get('profile') if isinstance(config, dict) else None
        return (isinstance(profile, dict) and config.get('hud_hidden_declared') is True
                and profile.get('mode') == 'vehicle_buttons' and profile.get('steering') == 'stick'
                and profile.get('hudProfile') == 'black_russia_scooter_v1')

    def start_vehicle(self, job, body):
        """Separate speed-observed, attached-camera vehicle planner.

        The ready-map gate and all source bindings are retained. Plans alone
        cannot acquire Android input or promote an observer or pedestrian run.
        """
        from motor_worker.route_reference_view import reference_rotations
        from motor_worker.vehicle_route import ConservativeTempoReference, VehicleRouteFollower
        from scripts.pilot.route_hud_profile import load_speed_reference

        required = {'id', 'captureEpoch', 'width', 'height', 'sceneConfirmed',
                    'vehicleCameraAssumptionConfirmed', 'cameraFollowsBodyConfirmed',
                    'hudProfile', 'maxSpeedKmh', 'cameraTracking', 'cameraControl', 'clientVersion'}
        if (type(body) is not dict or not required <= body.keys()
                or not body.keys() <= required | {'startMode', 'diagnosticFrames', 'maxSeconds', 'expectedSource', 'speedMode'}
                or body.get('vehicleCameraAssumptionConfirmed') is not True
                or body.get('cameraFollowsBodyConfirmed') is not True
                or body.get('hudProfile') != 'black_russia_scooter_v1'
                or type(body.get('maxSpeedKmh')) is not int or not 1 <= body['maxSpeedKmh'] <= 50
                or body.get('cameraTracking') is not True
                or body.get('cameraControl') != 'continuous_drag_v1'
                or body.get('clientVersion') != 'vehicle_live_v1'
                or body.get('speedMode', 'recorded_hud') not in ('recorded_hud', 'visual_tempo_live_hud')
                or body.get('startMode', 'beginning') not in {'beginning', 'recognized_route'}
                or 'maxSeconds' in body and (type(body['maxSeconds']) is not int or not 60 <= body['maxSeconds'] <= 1800)
                or type(body.get('diagnosticFrames', False)) is not bool):
            raise ValueError('vehicle_explicit_confirmation_required')
        manifest = checked_json(job / 'input/manifest.json')
        speed_mode = body.get('speedMode', 'recorded_hud')
        visual_tempo = speed_mode == 'visual_tempo_live_hud'
        if visual_tempo and (body['maxSpeedKmh'] != ConservativeTempoReference.MAX_SPEED_KMH
                or not self._visual_tempo_source(job, manifest=manifest)
                or not isinstance(body.get('expectedSource'), dict)
                or body['expectedSource'].get('runtime_family') != 'reference_lk'):
            raise ValueError('vehicle_visual_tempo_unavailable')
        profile = manifest.get('config', {}).get('profile', {})
        if (type(profile) is not dict or profile.get('mode') != 'vehicle_buttons'
                or profile.get('steering') != 'stick' or profile.get('hudProfile') != body['hudProfile']):
            raise ValueError('vehicle_source_profile_mismatch')
        request = {key: body[key] for key in ('id', 'captureEpoch', 'width', 'height', 'sceneConfirmed')}
        if 'expectedSource' in body:
            request['expectedSource'] = body['expectedSource']
        settings = {key: body.get(key, False if key == 'diagnosticFrames' else 'beginning')
                    for key in ('startMode', 'maxSpeedKmh', 'diagnosticFrames', 'hudProfile')}
        settings['maxSeconds'] = body.get('maxSeconds')
        settings['speedMode'] = speed_mode
        self._expire()
        if self.live and self.live['id'] == request['id']:
            if 'vehicle' not in self.live:
                raise ValueError('vehicle_observer_cannot_be_promoted')
            if self.live.get('vehicle_settings') != settings:
                raise ValueError('vehicle_settings_changed')
        reference = None if visual_tempo else load_speed_reference(job)
        if not visual_tempo and reference is None:
            raise ValueError('vehicle_source_speed_not_prepared')
        self.start_live(job, request, observation_only=False)
        try:
            if 'vehicle' not in self.live:
                route = self.live['tracker'].route
                if visual_tempo:
                    if self.live.get('runtime_family') != 'reference_lk':
                        raise ValueError('vehicle_visual_tempo_unavailable')
                    reference = ConservativeTempoReference(route)
                views = reference_rotations(self.live.get('geometry_path', job/'geometry.json'),
                                            route, self.live['geometry_sha256'])
                budget = body.get('maxSeconds', min(1800, max(180,
                    math.ceil((route.source_seconds[-1] - route.source_seconds[0]) * 5 + 30))))
                self.live['vehicle'] = VehicleRouteFollower(route, reference, clock=self.clock,
                    reference_rotations=views, start_mode=settings['startMode'],
                    max_seconds=budget, max_speed_kmh=body['maxSpeedKmh'])
                self.live['vehicle_settings'] = settings
                self.live['deadline'] = self.clock() + budget
                self.live['observation_limit'] = budget * 30
                self.live['motion_protocol'] = 'applied_vehicle_v1'
                if body.get('diagnosticFrames'):
                    from scripts.pilot.walk_diagnostics import WalkFrameArchive
                    self.live['frame_archive'] = WalkFrameArchive(job, body['id'], clock=self.clock,
                        geometry_sha256=self.live['geometry_sha256'], capture_epoch=body['captureEpoch'])
            return dict(self.live_status(), mode='vehicle_camera_trace_v1', physicalActions=0,
                        maxSeconds=self.live['vehicle'].max_seconds, maxSpeedKmh=body['maxSpeedKmh'],
                        startMode=settings['startMode'], cameraTracking=True,
                        cameraControl='continuous_drag_v1', cameraFollowsBodyConfirmed=True,
                        hudProfile=body['hudProfile'], speedMode=speed_mode, observationProtocol='jpeg_binary_v1',
                        motionProtocol='applied_vehicle_v1', clientVersion='vehicle_live_v1')
        except BaseException:
            self._retire_live(self.live, self.clock())
            raise
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
        if self.live.get('motion_protocol') in {'applied_stick_v1', 'applied_vehicle_v1'} and 'motionActive' not in body:
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
        self._validate_live_source(session)
        if session.get('runtime_family') == 'reference_lk':
            from scripts.pilot.route_preparation_source import attempt_cancelled
            if attempt_cancelled(job, session['preparation_folder']):
                self._retire_live(session, self.clock())
                raise RuntimeError('cancelled')
        session['sequence'] = body['sequence']
        session['observations'] += 1
        if session['observations'] > session.get('observation_limit',1200):
            self._retire_live(session, self.clock())
            raise ValueError('route_live_observation_quota')
        frame = PolicyFrame(session['epoch'], body['sequence'], now, 960, 540, rgb)
        pose = session['tracker'].observe(frame, episode_id=session['episode'], goal_revision=session['goal'], scene='active')
        elapsed = (self.clock()-now)*1000
        values = asdict(pose)
        if session.get('runtime_family') == 'reference_lk':
            from motor_worker.route_reference_lk import REFERENCE_LK_SEARCH_POLICY, REFERENCE_LK_VERIFICATION_POLICY
            verification_policy = getattr(session['tracker'], 'verification_policy', REFERENCE_LK_VERIFICATION_POLICY)
            search_policy = REFERENCE_LK_SEARCH_POLICY
        else:
            verification_policy, search_policy = PNP_VERIFICATION_POLICY, COARSE_SEARCH_POLICY
        from scripts.pilot.walk_diagnostics import bounded_localization_diagnostic
        diagnostic = bounded_localization_diagnostic(getattr(session['tracker'], 'last_diagnostic', None),
            reason=pose.reason, source_family=session.get('runtime_family', 'legacy_sparse'))
        if diagnostic['method'] == 'descriptor_pnp':
            search_policy = COARSE_SEARCH_POLICY
        result = dict(id=session['id'], sequence=body['sequence'], jpegSha256=hashlib.sha256(raw).hexdigest(),
            captureEpoch=body['captureEpoch'], pose=values, computeMs=elapsed, geometrySha256=session['geometry_sha256'],
            method=diagnostic['method'],localizationDiagnostic=diagnostic,
            verificationPolicy=verification_policy,
            confirmationPolicy=getattr(session['tracker'], 'confirmation_policy', None),
            confirmationRuntimeSha256=getattr(session['tracker'], 'confirmation_runtime_sha256', None),
            coarseSearchPolicy=search_policy,
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
        if 'vehicle' in session:
            from scripts.pilot.route_hud_profile import read_live_speed
            speed = read_live_speed(image, epoch=session['epoch'], sequence=body['sequence'],
                received_at=now, jpeg_sha256=result['jpegSha256'])
            speed = {**speed, 'source_rgb_sha256': pose.source_rgb_sha256}
            result['vehicle'] = session['vehicle'].observe(pose, speed, motion_active=body.get('motionActive'))
            result['vehicle']['motionActive'] = body.get('motionActive')
            result['vehicle']['motionSeconds'] = session['vehicle'].motion_seconds
            result['speedObservation'] = speed
            result['computeMs'] = (self.clock() - now) * 1000
        if session.get('frame_archive'):
            session['frame_archive'].offer(raw,sequence=body['sequence'],pose=pose,plan=result.get('walk', result.get('vehicle')),
                method=result['method'],compute_ms=elapsed,diagnostic=diagnostic)
        metadata = session.get('metadata_ring')
        if metadata is not None:
            try:
                metadata.offer(pose=values, diagnostic=diagnostic,
                    plan=result.get('walk', result.get('vehicle')), compute_ms=result['computeMs'],
                    source_binding=session.get('source_binding') or
                        dict(geometry_sha256=session['geometry_sha256']))
            except Exception:
                pass
        return result
