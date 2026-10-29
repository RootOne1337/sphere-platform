"""Opt-in loopback reconstruction jobs for the local teaching workbench.

One active job, fixed filenames, bounded chunks, per-job capabilities and origin
checks. No Sphere credential, remote URL, command, Android or native-input API.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.alternative_geometry import alternative, list_alternatives
from scripts.pilot.reconstruct_surface import (
    SURFACE_TERMINAL,
    source_model,
    surface_options,
    surface_output,
    tools_available,
)
from scripts.pilot.reconstruction_quality import export_interval
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_motion_audit import audit as audit_camera_motion
from scripts.pilot.route_workspace import RouteWorkspaces
from scripts.pilot.surface_asset import MAX_BYTES, MAX_FACES, validate_glb

ROOT = Path(__file__).resolve().parents[2]
LIMITS = {'manifest.json': 65536, 'frames.jsonl': 16 * 1024**2,
          'inputs.jsonl': 8 * 1024**2, 'COMPLETE': 1024, 'video.h264': 2**31}
TERMINAL = {'complete', 'sparse_complete', 'failed', 'cancelled', 'quality_rejected', 'review_required', 'partial_scene'}
IDENTITY = re.compile(r'^[0-9a-f]{32}$')


class AccessDenied(PermissionError):
    """Origin/capability denial, distinct from Windows file sharing failures."""


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Jobs:
    def __init__(self, folder, python):
        self.folder, self.python = folder, python
        folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.processes = {}
        # Sparse descriptor export and live matching must use the exact same
        # OpenCV/extractor runtime. The heavy reconstruction interpreter can
        # have a different GPU stack and is deliberately kept separate.
        self.navigation = RouteWorkspaces(folder, Path(sys.executable))
        # An interrupted job cannot be silently resumed or retrained on restart.
        for path in folder.glob('*/state.json'):
            if json.loads(path.read_text('utf-8'))['phase'] not in TERMINAL:
                write_json(path, dict(phase='failed', error='worker_service_restarted', updated_at=time.time()))
        for path in [*folder.glob('*/surface/state.json'), *folder.glob('*/fragments/*/state.json')]:
            if json.loads(path.read_text('utf-8'))['phase'] not in SURFACE_TERMINAL:
                (path.parent / 'CANCEL').touch(exist_ok=True)
                write_json(path, dict(phase='failed', error='surface_service_restarted', updated_at=time.time()))
        for control_path in folder.glob('*/control.json'):
            control = json.loads(control_path.read_text('utf-8'))
            job = control_path.parent
            phase = json.loads((job / 'state.json').read_text('utf-8'))['phase'] if (job / 'state.json').is_file() else None
            if (control.get('prepare_route') is True
                    and (phase in {'complete', 'sparse_complete'} or phase == 'failed' and (job / 'sparse-receipt.json').is_file())
                    and not (job / 'navigation/active.json').exists()
                    and not (job / 'route-pipeline-refusal.json').exists()):
                write_json(job / 'route-pipeline-refusal.json', dict(error='route_preparation_interrupted'))

    def path(self, identity):
        if not IDENTITY.fullmatch(identity):
            raise ValueError('invalid_job_id')
        return self.folder / identity

    def status(self, job):
        result = json.loads((job / 'state.json').read_text('utf-8'))
        if (job / 'quality.json').is_file():
            result['quality'] = json.loads((job / 'quality.json').read_text('utf-8'))
        result['geometry_available'] = (job / 'geometry.json').is_file()
        # Presence is a hint for the UI, not validation. The exporter verifies
        # every receipt binding before and after reading the model.
        result['sparse_available'] = (result['phase'] in TERMINAL
                                      and (job / 'sparse-receipt.json').is_file()
                                      and not (job / 'sparse-receipt.json').is_symlink())
        result['dense_available'] = result['phase'] in {'complete', 'quality_rejected', 'review_required', 'partial_scene'} and (job / 'COMPLETE').is_file()
        if result['dense_available']:
            appearance = self.appearance(job)
            result['appearance'] = ({**appearance['summary'], 'views': [
                dict(image=view['image'], psnr=view['psnr'], ssim=view['ssim']) for view in appearance['views']]}
                if appearance else dict(state='unverified'))
            if not appearance:
                result['phase'] = 'review_required'
            elif appearance['summary']['state'] == 'rejected':
                result['phase'] = 'quality_rejected'
                result['error'] = 'dense_visual_quality_gate_failed'
            elif result.get('quality', {}).get('registered', 0) < result.get('quality', {}).get('selected', 0):
                result['phase'] = 'partial_scene'
        partial = self.partial(job) if result['phase'] == 'failed' else None
        result['dense_partial_available'] = partial is not None
        if partial:
            result['checkpoint'] = partial
        result['surface'] = self.surface_status(job)
        result['fragments'] = [self.surface_status(job, p.name) for p in sorted((job / 'fragments').glob('*'))
                               if p.is_dir() and IDENTITY.fullmatch(p.name)][:24]
        result['fragments'] = [item for item in result['fragments'] if item]
        result['fragments'].sort(key=lambda item: (item.get('fragment', {}).get('first_view', 0), item['id']))
        result['surface_supported'] = tools_available()
        result['navigation'] = self.navigation.status(job)
        if (result['phase'] in {'complete', 'sparse_complete'} or result['phase'] == 'failed' and result['sparse_available']) and result['navigation']['phase'] == 'not_prepared':
            control = json.loads((job / 'control.json').read_text('utf-8'))
            if control.get('prepare_route') is True:
                refusal = job / 'route-pipeline-refusal.json'
                if refusal.is_file():
                    result['navigation']['error'] = json.loads(refusal.read_text('utf-8'))['error']
                else:
                    result['navigation']['phase'] = 'pending_auto_prepare'
        geometry = job / 'geometry.json'
        if geometry.is_file() and not geometry.is_symlink() and geometry.stat().st_size <= 16 * 1024**2:
            try:
                motion = audit_camera_motion(json.loads(geometry.read_text('utf-8')))
                result['camera_motion'] = dict(warning=motion['warning'], rapid_reversals=len(motion['rapid_reversals']),
                    speed_outliers=len(motion['speed_outliers']),
                    heuristic_only=True, navigation_qualified=False)
            except (KeyError, TypeError, ValueError):
                result['camera_motion'] = dict(warning='camera_motion_unverified', navigation_qualified=False)
        return result

    def surface_status(self, job, fragment=None):
        folder = surface_output(job, fragment)
        identity = dict(id=fragment) if fragment else {}
        if folder.is_symlink() or folder.parent.is_symlink() or not folder.resolve().is_relative_to(job.resolve()):
            raise ValueError('surface_fragment_path_invalid')
        if not (folder / 'state.json').is_file():
            return None
        state = json.loads((folder / 'state.json').read_text('utf-8'))
        if fragment:
            state['id'] = fragment
        if (folder / 'options.json').is_file():
            if (folder / 'options.json').stat().st_size > 1024:
                raise ValueError('surface_options_quota')
            state['fragment'] = json.loads((folder / 'options.json').read_text('utf-8'))
        if (folder / 'CANCEL').exists() and state['phase'] in {'ready', 'review_required'}:
            return dict(**identity, phase='cancelled', error='surface_cancelled_before_admission', available=False)
        if state['phase'] in {'ready', 'review_required'}:
            try:
                receipt = folder / 'result.json'
                if receipt.is_symlink() or receipt.stat().st_size > 65536:
                    raise ValueError('surface_result_invalid')
                item = json.loads(receipt.read_text('utf-8'))
                if (item['schema'] != 'sphere-observed-surface-v1' or item['file'] != 'scene.glb'
                        or not re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
                        or type(item['bytes']) is not int or not 0 < item['bytes'] <= MAX_BYTES
                        or type(item['triangles']) is not int or not 0 < item['triangles'] <= MAX_FACES
                        or item['metric_scale'] is not None or item['navigation_qualified'] is not False
                        or item['geometry_sha256'] != hashlib.sha256((job / 'geometry.json').read_bytes()).hexdigest()
                        or item['source_manifest_sha256'] != hashlib.sha256((job / 'input/manifest.json').read_bytes()).hexdigest()
                        or not 3 <= len(item['source_images']) <= 96
                        or len(set(item['source_images'])) != len(item['source_images'])
                        or any(not re.fullmatch(r'[0-9]{8}\.png', name) for name in item['source_images'])):
                    raise ValueError('surface_result_invalid')
                state['result'] = {key: item[key] for key in ('sha256', 'bytes', 'triangles', 'vertices',
                    'textures', 'texture_pixels', 'source_images', 'mesh_faces', 'unknown_faces', 'seconds')}
                state['available'] = True
                review_file = folder / 'visual-review.json'
                if review_file.is_file() and not review_file.is_symlink() and review_file.stat().st_size <= 8192:
                    review = json.loads(review_file.read_text('utf-8'))
                    if (review.get('schema') == 'sphere-surface-visual-review-v1'
                            and review.get('asset_sha256') == item['sha256']
                            and review.get('state') in {'issues_found', 'limited_preview'}
                            and isinstance(review.get('issues'), list)
                            and set(review['issues']) <= {'holes', 'occluding_surfaces', 'stretched_triangles', 'pose_inconsistency'}):
                        state['visual_review'] = dict(state=review['state'], issues=review['issues'])
            except (OSError, KeyError, TypeError, ValueError):
                return dict(**identity, phase='failed', error='surface_result_binding_changed', available=False)
        return state

    def source_preview(self, job, name):
        from PIL import Image
        from scripts.pilot.prepare_route_workspace import route_source_model

        if not re.fullmatch(r'[0-9]{8}\.png', name):
            raise ValueError('source_preview_invalid')
        provenance = job / 'prepared/reconstruction-input.json'
        if provenance.is_symlink() or provenance.stat().st_size > 1024**2:
            raise ValueError('source_preview_invalid')
        route_source_model(job)  # Bind sparse or complete scene before showing a comparison.
        records = json.loads(provenance.read_text('utf-8'))['images']
        entry = next((row for row in records if row['image'] == 'images/' + name), None)
        path = job / 'prepared/images' / name
        if (not entry or path.is_symlink() or not path.resolve().is_relative_to(job.resolve())
                or not 0 < path.stat().st_size <= 8 * 1024**2):
            raise ValueError('source_preview_invalid')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != entry['png_sha256']:
            raise ValueError('source_preview_changed')
        with Image.open(io.BytesIO(body)) as source:
            if source.width * source.height > 8 * 1024**2:
                raise ValueError('source_preview_pixel_quota')
            image = source.convert('RGB')
        image.thumbnail((960, 960), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format='JPEG', quality=88)
        return out.getvalue()

    def active(self, job):
        state = self.status(job)
        live = self.navigation.live_status()
        return (state['phase'] not in TERMINAL or any(item['phase'] not in SURFACE_TERMINAL
                for item in [state['surface'], *state['fragments']] if item)
                or self.navigation.preparing(job) or live.get('job') == job.name)

    def surface_asset(self, job, fragment=None):
        status = self.surface_status(job, fragment)
        if not status or not status.get('available'):
            raise ValueError('surface_not_ready')
        path = surface_output(job, fragment) / 'scene.glb'
        if (path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(job.resolve())
                or path.stat().st_size != status['result']['bytes']):
            raise ValueError('surface_asset_changed')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != status['result']['sha256']:
            raise ValueError('surface_asset_changed')
        validate_glb(body)
        return body

    def start_surface(self, job, body=None, fragment=None):
        status = self.status(job)
        if self.surface_status(job, fragment):
            return status  # Re-read an existing intent; never repeat ambiguous work.
        if status['phase'] not in TERMINAL or not status['geometry_available']:
            raise ValueError('surface_completed_source_required')
        source_model(job)
        if not isinstance(body if body is not None else {}, dict):
            raise ValueError('surface_fragment_range_invalid')
        geometry = json.loads((job / 'geometry.json').read_text('utf-8'))
        options = surface_options(body or {}, len(geometry['cameras']))
        for item in [status['surface'], *status['fragments']]:
            if item and item.get('fragment') == options:
                return status
        if fragment and len(list((job / 'fragments').glob('*'))) >= 24:
            raise ValueError('surface_fragment_quota')
        if not tools_available():
            raise ValueError('surface_openmvs_cpu_not_installed')
        if any(self.active(p) for p in self.folder.iterdir() if p.is_dir()):
            raise ValueError('one_active_job_only')
        if evaluate(collect(ROOT)):
            raise ValueError('resource_guard')
        folder = surface_output(job, fragment)
        folder.parent.mkdir(exist_ok=True)
        folder.mkdir()
        with (folder / 'START').open('x') as file:
            file.write(str(time.time()))
        write_json(folder / 'options.json', options)
        write_json(folder / 'state.json', dict(phase='starting', updated_at=time.time()))
        log = (folder / 'worker.log').open('xb')
        try:
            process = subprocess.Popen([str(self.python), '-m', 'scripts.pilot.reconstruct_surface',
                '--job', str(job), *(['--fragment', fragment] if fragment else [])], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception:
            write_json(folder / 'state.json', dict(phase='failed', error='surface_start_not_confirmed'))
            raise
        finally:
            log.close()
        self.processes[job.name + ':surface:' + (fragment or 'legacy')] = process
        threading.Thread(target=self.monitor_surface, args=(job, process, fragment), daemon=True).start()
        return self.status(job)

    def monitor_surface(self, job, process, fragment=None):
        folder, deadline = surface_output(job, fragment), time.monotonic() + 1830
        while process.poll() is None:
            time.sleep(3)
            reason = ('cancelled' if (folder / 'CANCEL').exists() else
                      'surface_time_budget' if time.monotonic() > deadline else
                      'surface_log_quota' if (folder / 'worker.log').stat().st_size > 32 * 1024**2 else
                      'resource_guard' if evaluate(collect(ROOT)) else None)
            if reason:
                (folder / 'CANCEL').touch(exist_ok=True)
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=15, check=False)
                else:
                    process.kill()
                process.wait(15)
                write_json(folder / 'state.json', dict(phase='cancelled' if reason == 'cancelled' else 'failed', error=reason))
                return
        with self.lock:
            if self.surface_status(job, fragment)['phase'] not in SURFACE_TERMINAL:
                write_json(folder / 'state.json', dict(phase='failed', error='surface_worker_exited_without_completion'))

    def appearance(self, job):
        from scripts.pilot.reconstruction_quality import reference_quality

        path = job / 'appearance.json'
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16384:
            return None
        try:
            data = json.loads(path.read_text('utf-8'))
            result = json.loads((job / 'result.json').read_text('utf-8'))
            if (data.get('schema') != 'sphere-scene-appearance-v1'
                    or data.get('ply_sha256') != result['ply_sha256']
                    or data.get('geometry_sha256') != result['geometry_sha256']):
                return None
            views = data['views']
            if len({view['image'] for view in views}) != len(views):
                return None
            expected = reference_quality(dict(schema='sphere-reference-render-evaluation-v1',
                training=False, held_out=False, resolution_limit=960, views=views))
            if data['summary'] != expected:
                return None
            for view in views:
                if not re.fullmatch(r'[0-9]{8}\.png', view['image']):
                    return None
                for kind in ('source', 'render'):
                    entry = view[kind]
                    if (not re.fullmatch(r'reference-evaluation(?:-attempt-[12])?/[0-9]{8}-' + kind + r'\.png', entry['file'])
                            or Path(entry['file']).name != view['image'][:-4] + '-' + kind + '.png'
                            or not re.fullmatch(r'[0-9a-f]{64}', entry['sha256'])
                            or type(entry['bytes']) is not int or not 0 < entry['bytes'] <= 4 * 1024**2):
                        return None
            return data
        except (KeyError, TypeError, ValueError, OSError):
            return None

    def reference_image(self, job, index, kind):
        data = self.appearance(job)
        if data is None or kind not in {'source', 'render'} or not 0 <= index < len(data['views']):
            raise ValueError('reference_image_unavailable')
        entry = data['views'][index][kind]
        path = job / entry['file']
        if (path.is_symlink() or path.parent.is_symlink() or not path.resolve().is_relative_to(job.resolve())
                or path.stat().st_size != entry['bytes']):
            raise ValueError('reference_image_changed')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != entry['sha256']:
            raise ValueError('reference_image_changed')
        return body

    def partial(self, job):
        path = job / 'checkpoint.json'
        if not path.is_file() or path.stat().st_size > 4096:
            return None
        item = json.loads(path.read_text('utf-8'))
        if (item.get('partial') is not True or not re.fullmatch(r'dense(?:-attempt-[12])?/scene_[0-9]+\.ply', item.get('file', ''))
                or not re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', ''))
                or type(item.get('steps')) is not int or type(item.get('target_steps')) is not int
                or not 0 < item['steps'] < item['target_steps']):
            return None
        file = job / item['file']
        quality = json.loads((job / 'quality.json').read_text('utf-8'))
        if type(item.get('vertices')) is not int or item['vertices'] < max(300, int(quality['points'] * .25)):
            return None
        if file.is_symlink() or not file.is_file() or not 1024 < file.stat().st_size <= 256 * 1024**2:
            return None
        return item

    def authorize(self, job, key):
        if not (job / 'control.json').is_file():
            raise ValueError('job_not_found')
        control = json.loads((job / 'control.json').read_text('utf-8'))
        if not hmac.compare_digest(control['key_sha256'], hashlib.sha256(key.encode()).hexdigest()):
            raise AccessDenied('job_capability_required')
        return control

    def create(self, body):
        if not isinstance(body, dict):
            raise ValueError('object_required')
        identity, key = body.get('id', ''), body.get('key', '')
        if not isinstance(key, str) or not re.fullmatch(r'[0-9a-f]{64}', key):
            raise ValueError('invalid_job_key')
        job = self.path(identity)
        if job.exists():
            self.authorize(job, key)
            return self.status(job)  # Same creation intent is read back, never repeated.
        if body.get('mask') not in {'none', 'avatar', 'game'}:
            raise ValueError('invalid_processing_options')
        if type(body.get('prepare_route', False)) is not bool:
            raise ValueError('invalid_route_pipeline_option')
        if type(body.get('route_only', False)) is not bool or body.get('route_only', False) and not body.get('prepare_route', False):
            raise ValueError('invalid_route_pipeline_option')
        export_interval(body.get('steps'))
        if len(list(self.folder.iterdir())) >= 32:
            raise ValueError('retained_job_quota_export_or_archive_locally_first')
        for path in self.folder.iterdir():
            if not path.is_dir() or self.status(path)['phase'] != 'uploading':
                continue
            activity = max([entry.stat().st_mtime for entry in (path / 'input').iterdir()]
                           + [(path / 'control.json').stat().st_mtime])
            if time.time() - activity > 1800:
                write_json(path / 'state.json', dict(phase='failed', error='upload_idle_30_minutes'))
        if any(self.active(p) for p in self.folder.iterdir() if p.is_dir()):
            raise ValueError('one_active_job_only')
        if evaluate(collect(ROOT)):
            raise ValueError('resource_guard')
        job.mkdir()
        (job / 'input').mkdir()
        write_json(job / 'control.json', dict(key_sha256=hashlib.sha256(key.encode()).hexdigest(),
                   mask=body['mask'], steps=body['steps'], prepare_route=body.get('prepare_route', False),
                   route_only=body.get('route_only', False), created_at=time.time()))
        write_json(job / 'state.json', dict(phase='uploading', updated_at=time.time()))
        return self.status(job)

    def upload(self, job, name, offset, data):
        if name not in LIMITS or type(offset) is not int or offset < 0:
            raise ValueError('invalid_upload_target')
        if self.status(job)['phase'] != 'uploading':
            raise ValueError('upload_closed')
        path = job / 'input' / name
        size = path.stat().st_size if path.exists() else 0
        if size != offset:
            raise ValueError('upload_offset_mismatch_read_offsets_before_retry')
        if not data or size + len(data) > LIMITS[name]:
            raise ValueError('upload_byte_quota')
        with path.open('ab') as file:
            file.write(data)
        return dict(offset=size + len(data))

    def start(self, job, control):
        status = self.status(job)
        if status['phase'] != 'uploading':
            return status
        if any(not (job / 'input' / name).is_file() for name in LIMITS):
            raise ValueError('source_files_missing')
        if evaluate(collect(ROOT)):
            raise ValueError('resource_guard')
        # Durable one-shot intent precedes process creation. Ambiguity is failure.
        with (job / 'START').open('x') as file:
            file.write(str(time.time()))
        write_json(job / 'state.json', dict(phase='starting', updated_at=time.time()))
        log = (job / 'worker.log').open('xb')
        try:
            command = [str(self.python), '-m', 'scripts.pilot.reconstruct_route',
                     '--job', str(job), '--mask', control['mask'], '--steps', str(control['steps'])]
            if control.get('route_only', False):
                command.append('--route-only')
            process = subprocess.Popen(command,
                     cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception:
            write_json(job / 'state.json', dict(phase='failed', error='worker_start_not_confirmed'))
            raise
        finally:
            log.close()
        self.processes[job.name] = process
        threading.Thread(target=self.monitor, args=(job, process), daemon=True).start()
        return self.status(job)

    def monitor(self, job, process):
        deadline = time.monotonic() + 2400
        while process.poll() is None:
            time.sleep(3)
            reason = None
            if (job / 'CANCEL').exists():
                reason = 'cancelled'
            elif time.monotonic() > deadline:
                reason = 'worker_timeout'
            elif (job / 'worker.log').stat().st_size > 32 * 1024**2:
                reason = 'worker_log_quota'
            elif evaluate(collect(ROOT)):
                reason = 'resource_guard'
            if reason:
                # Own known PID only; also terminate the own Brush child on Windows.
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   capture_output=True, timeout=15, check=False)
                else:
                    process.kill()
                process.wait(15)
                write_json(job / 'state.json', dict(phase='cancelled' if reason == 'cancelled' else 'failed', error=reason))
                return
        if self.status(job)['phase'] not in TERMINAL:
            write_json(job / 'state.json', dict(phase='failed', error='worker_exited_without_completion'))
        control = json.loads((job/'control.json').read_text('utf-8'))
        final = self.status(job)
        if (control.get('prepare_route') is True
                and (final['phase'] in {'complete', 'sparse_complete'} or final['phase'] == 'failed' and final['sparse_available'])):
            with self.lock:
                if not any(self.active(p) for p in self.folder.iterdir() if p.is_dir()):
                    identity = hashlib.sha256((job.name+':initial-route').encode()).hexdigest()[:32]
                    try:
                        self.navigation.prepare(job, dict(id=identity))
                    except (ValueError, RuntimeError):
                        write_json(job/'route-pipeline-refusal.json', dict(error='route_preparation_not_started'))
                else:
                    write_json(job/'route-pipeline-refusal.json', dict(error='route_preparation_busy'))


def handler(jobs, origin, port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass  # Capabilities and raw records never enter access logs.

        def allowed(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}':
                raise AccessDenied('loopback_host_required')
            if self.headers.get('Origin') not in {None, origin}:
                raise AccessDenied('origin_denied')
            if self.headers.get('X-Sphere-Reconstruction') != '1':
                raise AccessDenied('explicit_local_client_required')

        def reply(self, code, body, content_type='application/json'):
            if isinstance(body, dict):
                body = json.dumps(body, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if self.headers.get('Origin') == origin:
                self.send_header('Access-Control-Allow-Origin', origin)
                self.send_header('Vary', 'Origin')
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}' or self.headers.get('Origin') != origin:
                self.reply(403, {'error': 'origin_denied'})
                return
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-Sphere-Reconstruction, X-Job-Key, X-Upload-Offset')
            self.end_headers()

        def body(self, maximum):
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('chunked_request_not_supported')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= maximum:
                raise ValueError('request_byte_quota')
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError('request_truncated')
            return data

        def do_GET(self):
            self.dispatch('GET')

        def do_POST(self):
            self.dispatch('POST')

        def do_PUT(self):
            self.dispatch('PUT')

        def dispatch(self, method):
            self.connection.settimeout(20)
            try:
                self.allowed()
                parts = self.path.strip('/').split('/')
                if method == 'GET' and parts == ['health']:
                    self.reply(200, dict(service='sphere-reconstruction-v1', one_active_job=True))
                    return
                with jobs.lock:
                    if method == 'POST' and parts == ['jobs']:
                        self.reply(200, jobs.create(json.loads(self.body(4096))))
                        return
                    if len(parts) < 2 or parts[0] != 'jobs':
                        raise ValueError('unknown_endpoint')
                    job = jobs.path(parts[1])
                    control = jobs.authorize(job, self.headers.get('X-Job-Key', ''))
                    if method == 'GET' and len(parts) == 2:
                        self.reply(200, jobs.status(job))
                    elif method == 'GET' and parts[2:] == ['offsets']:
                        self.reply(200, {name: (job / 'input' / name).stat().st_size if (job / 'input' / name).exists() else 0 for name in LIMITS})
                    elif method == 'GET' and parts[2:] == ['navigation']:
                        self.reply(200, jobs.navigation.status(job))
                    elif method == 'GET' and parts[2:] == ['geometry-alternatives']:
                        self.reply(200, {'alternatives': list_alternatives(job)})
                    elif method == 'GET' and len(parts) == 4 and parts[2] == 'geometry-alternatives':
                        body, _ = alternative(job, parts[3])
                        self.reply(200, body)
                    elif method == 'POST' and parts[2:] == ['navigation', 'prepare']:
                        body = json.loads(self.body(1024))
                        current = jobs.navigation.current(job)
                        same = type(body) is dict and current is not None and current.name == body.get('id')
                        if not same and any(jobs.active(p) for p in jobs.folder.iterdir() if p.is_dir()):
                            raise ValueError('one_active_job_only')
                        self.reply(200, jobs.navigation.prepare(job, body))
                    elif method == 'POST' and parts[2:] == ['navigation', 'start']:
                        body = json.loads(self.body(1024))
                        live = jobs.navigation.live_status()
                        same = type(body) is dict and live.get('id') == body.get('id') and live.get('job') == job.name
                        if not same and any(jobs.active(p) for p in jobs.folder.iterdir() if p.is_dir()):
                            raise ValueError('one_active_job_only')
                        self.reply(200, jobs.navigation.start_live(job, body))
                    elif method == 'POST' and parts[2:] == ['navigation', 'walk-start']:
                        body = json.loads(self.body(1024))
                        live = jobs.navigation.live_status()
                        same = type(body) is dict and live.get('id') == body.get('id') and live.get('job') == job.name
                        if not same and any(jobs.active(p) for p in jobs.folder.iterdir() if p.is_dir()):
                            raise ValueError('one_active_job_only')
                        self.reply(200, jobs.navigation.start_walk(job, body))
                    elif method == 'POST' and parts[2:] == ['navigation', 'replay-start']:
                        body=json.loads(self.body(1024))
                        live=jobs.navigation.live_status()
                        same=type(body) is dict and live.get('id')==body.get('id') and live.get('job')==job.name
                        if not same and any(jobs.active(p) for p in jobs.folder.iterdir() if p.is_dir()):
                            raise ValueError('one_active_job_only')
                        self.reply(200,jobs.navigation.start_replay(job,body))
                    elif method == 'POST' and parts[2:] == ['navigation', 'replay-observe']:
                        self.reply(200,jobs.navigation.observe(job,json.loads(self.body(768*1024)),mode='recorded_replay'))
                    elif method == 'POST' and parts[2:] == ['navigation', 'replay-stop']:
                        self.reply(200,jobs.navigation.stop_live(job,json.loads(self.body(1024)),mode='recorded_replay'))
                    elif method == 'POST' and parts[2:] == ['navigation', 'observe']:
                        self.reply(200, jobs.navigation.observe(job, json.loads(self.body(768*1024))))
                    elif method == 'POST' and parts[2:] == ['navigation', 'stop']:
                        self.reply(200, jobs.navigation.stop_live(job, json.loads(self.body(1024))))
                    elif method == 'PUT' and len(parts) == 4 and parts[2] == 'input':
                        self.reply(200, jobs.upload(job, parts[3], int(self.headers.get('X-Upload-Offset', '-1')), self.body(1024**2)))
                    elif method == 'POST' and parts[2:] == ['start']:
                        self.body(1024)
                        self.reply(200, jobs.start(job, control))
                    elif method == 'POST' and parts[2:] == ['cancel']:
                        self.body(1024)
                        (job / 'CANCEL').touch(exist_ok=True)
                        if jobs.status(job)['phase'] == 'uploading':
                            write_json(job / 'state.json', dict(phase='cancelled'))
                        self.reply(200, jobs.status(job))
                    elif method == 'POST' and parts[2:] == ['surface', 'start']:
                        body = json.loads(self.body(1024))
                        self.reply(200, jobs.start_surface(job, body))
                    elif method == 'POST' and parts[2:] == ['surface', 'cancel']:
                        self.body(1024)
                        surface = jobs.surface_status(job)
                        if surface and surface['phase'] not in SURFACE_TERMINAL:
                            (job / 'surface/CANCEL').touch(exist_ok=True)
                        self.reply(200, jobs.status(job))
                    elif method == 'GET' and parts[2:] == ['surface']:
                        self.reply(200, jobs.surface_asset(job), 'model/gltf-binary')
                    elif method == 'GET' and len(parts) == 4 and parts[2] == 'frame':
                        self.reply(200, jobs.source_preview(job, parts[3]), 'image/jpeg')
                    elif method == 'POST' and len(parts) == 5 and parts[2] == 'fragments' and parts[4] == 'start':
                        if not IDENTITY.fullmatch(parts[3]):
                            raise ValueError('surface_fragment_id_invalid')
                        self.reply(200, jobs.start_surface(job, json.loads(self.body(1024)), parts[3]))
                    elif method == 'POST' and len(parts) == 5 and parts[2] == 'fragments' and parts[4] == 'cancel':
                        self.body(1024)
                        surface = jobs.surface_status(job, parts[3])
                        if surface and surface['phase'] not in SURFACE_TERMINAL:
                            (surface_output(job, parts[3]) / 'CANCEL').touch(exist_ok=True)
                        self.reply(200, jobs.status(job))
                    elif method == 'GET' and len(parts) == 4 and parts[2] == 'fragments':
                        self.reply(200, jobs.surface_asset(job, parts[3]), 'model/gltf-binary')
                    elif method == 'GET' and len(parts) == 5 and parts[2] == 'reference':
                        if not re.fullmatch(r'[0-8]', parts[3]):
                            raise ValueError('reference_image_unavailable')
                        self.reply(200, jobs.reference_image(job, int(parts[3]), parts[4]), 'image/png')
                    elif method == 'GET' and parts[2:] in (['geometry'], ['scene']):
                        scene = parts[2] == 'scene'
                        current = jobs.status(job)
                        if scene and not current['dense_available'] and not current['dense_partial_available']:
                            raise ValueError('dense_scene_not_complete')
                        path = job / 'dense/scene.ply' if scene else job / 'geometry.json'
                        if scene and current['dense_available']:
                            result = json.loads((job / 'result.json').read_text('utf-8'))
                            name = result.get('scene_file', 'dense/scene.ply')
                            if not re.fullmatch(r'dense(?:-attempt-[12])?/scene\.ply', name):
                                raise ValueError('invalid_scene_result_path')
                            path = job / name
                        if scene and not current['dense_available']:
                            partial = current['checkpoint']
                            path = job / partial['file']
                            with path.open('rb') as file:
                                if hashlib.file_digest(file, 'sha256').hexdigest() != partial['sha256']:
                                    raise ValueError('partial_scene_hash_changed')
                        maximum = 256 * 1024**2 if scene else 16 * 1024**2
                        if path.stat().st_size > maximum:
                            raise ValueError('output_byte_quota')
                        if scene:
                            self.send_response(200)
                            self.send_header('Content-Type', 'application/octet-stream')
                            self.send_header('Content-Length', str(path.stat().st_size))
                            self.send_header('Cache-Control', 'no-store')
                            if self.headers.get('Origin') == origin:
                                self.send_header('Access-Control-Allow-Origin', origin)
                            self.end_headers()
                            with path.open('rb') as file:
                                while chunk := file.read(1024**2):
                                    self.wfile.write(chunk)
                        else:
                            self.reply(200, path.read_bytes())
                    else:
                        raise ValueError('unknown_endpoint')
            except AccessDenied:
                self.reply(403, {'error': 'capability_or_origin_denied'})
            except PermissionError:
                self.close_connection = True
                self.reply(503, {'error': 'local_file_unavailable_inspect_job_status'})
            except (ValueError, FileExistsError) as error:
                self.close_connection = True
                self.reply(409, {'error': str(error)[:200]})
            except RuntimeError as error:
                self.close_connection = True
                if str(error) in {'resource_guard', 'cancelled'}:
                    self.reply(409, {'error': str(error)})
                else:
                    self.reply(500, {'error': 'local_operation_not_confirmed_inspect_job_status'})
            except FileNotFoundError:
                self.close_connection = True
                self.reply(409, {'error': 'job_file_unavailable'})
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                self.close_connection = True
            except Exception:
                self.close_connection = True
                self.reply(500, {'error': 'local_operation_not_confirmed_inspect_job_status'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=3342)
    parser.add_argument('--origin', default='http://127.0.0.1:3015')
    parser.add_argument('--jobs', type=Path, default=ROOT / '.local-pilot/reconstruction-jobs')
    parser.add_argument('--python', type=Path, default=ROOT / '.local-pilot/motor-amd-venv/Scripts/python.exe')
    args = parser.parse_args()
    jobs = Jobs(args.jobs.resolve(), args.python.resolve(strict=True))
    server = BoundedServer(('127.0.0.1', args.port), handler(jobs, args.origin, args.port))
    print(f'Reconstruction API: http://127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
