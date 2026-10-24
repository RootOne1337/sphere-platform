"""Opt-in loopback reconstruction jobs for the local teaching workbench.

One active job, fixed filenames, bounded chunks, per-job capabilities and origin
checks. No Sphere credential, remote URL, command, Android or native-input API.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.resource_guard import collect, evaluate

ROOT = Path(__file__).resolve().parents[2]
LIMITS = {'manifest.json': 65536, 'frames.jsonl': 16 * 1024**2,
          'inputs.jsonl': 8 * 1024**2, 'COMPLETE': 1024, 'video.h264': 2**31}
TERMINAL = {'complete', 'failed', 'cancelled'}
IDENTITY = re.compile(r'^[0-9a-f]{32}$')


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
        # An interrupted job cannot be silently resumed or retrained on restart.
        for path in folder.glob('*/state.json'):
            if json.loads(path.read_text('utf-8'))['phase'] not in TERMINAL:
                write_json(path, dict(phase='failed', error='worker_service_restarted', updated_at=time.time()))

    def path(self, identity):
        if not IDENTITY.fullmatch(identity):
            raise ValueError('invalid_job_id')
        return self.folder / identity

    def status(self, job):
        result = json.loads((job / 'state.json').read_text('utf-8'))
        if (job / 'quality.json').is_file():
            result['quality'] = json.loads((job / 'quality.json').read_text('utf-8'))
        result['geometry_available'] = (job / 'geometry.json').is_file()
        result['dense_available'] = result['phase'] == 'complete' and (job / 'COMPLETE').is_file()
        return result

    def authorize(self, job, key):
        control = json.loads((job / 'control.json').read_text('utf-8'))
        if not hmac.compare_digest(control['key_sha256'], hashlib.sha256(key.encode()).hexdigest()):
            raise PermissionError('job_capability_required')
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
        if body.get('mask') not in {'none', 'game'} or body.get('steps') not in {3000, 5000, 10000}:
            raise ValueError('invalid_processing_options')
        if len(list(self.folder.iterdir())) >= 12:
            raise ValueError('retained_job_quota_export_or_archive_locally_first')
        for path in self.folder.iterdir():
            if not path.is_dir() or self.status(path)['phase'] != 'uploading':
                continue
            activity = max([entry.stat().st_mtime for entry in (path / 'input').iterdir()]
                           + [(path / 'control.json').stat().st_mtime])
            if time.time() - activity > 1800:
                write_json(path / 'state.json', dict(phase='failed', error='upload_idle_30_minutes'))
        if any(self.status(p)['phase'] not in TERMINAL for p in self.folder.iterdir() if p.is_dir()):
            raise ValueError('one_active_job_only')
        if evaluate(collect(ROOT)):
            raise ValueError('resource_guard')
        job.mkdir()
        (job / 'input').mkdir()
        write_json(job / 'control.json', dict(key_sha256=hashlib.sha256(key.encode()).hexdigest(),
                   mask=body['mask'], steps=body['steps'], created_at=time.time()))
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
            process = subprocess.Popen([str(self.python), '-m', 'scripts.pilot.reconstruct_route',
                     '--job', str(job), '--mask', control['mask'], '--steps', str(control['steps'])],
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


def handler(jobs, origin, port):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass  # Capabilities and raw records never enter access logs.

        def allowed(self):
            if self.headers.get('Host') != f'127.0.0.1:{port}':
                raise PermissionError('loopback_host_required')
            if self.headers.get('Origin') not in {None, origin}:
                raise PermissionError('origin_denied')
            if self.headers.get('X-Sphere-Reconstruction') != '1':
                raise PermissionError('explicit_local_client_required')

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
                    elif method == 'GET' and parts[2:] in (['geometry'], ['scene']):
                        scene = parts[2] == 'scene'
                        if scene and not jobs.status(job)['dense_available']:
                            raise ValueError('dense_scene_not_complete')
                        path = job / 'dense/scene.ply' if scene else job / 'geometry.json'
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
            except PermissionError:
                self.reply(403, {'error': 'capability_or_origin_denied'})
            except (ValueError, FileNotFoundError, FileExistsError) as error:
                self.close_connection = True
                self.reply(409, {'error': str(error)[:200]})
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
