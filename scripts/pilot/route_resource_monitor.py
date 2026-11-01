"""Task-owned Windows volume proof; RAM, commit and disk are always fresh.

Admission takes a fresh bounded volume probe. During this same task only, one
background probe refreshes a healthy proof with a maximum age of 30 seconds.
Timeouts never invent health, retain old RAM or waive an observed warning.
There is no global cache, threshold change, thread pool or native input channel.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot import resource_guard

PROBE_INTERVAL_SECONDS = 10.
PROBE_TIMEOUT_SECONDS = 10.
PROOF_MAX_AGE_SECONDS = 30.


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def windows_volume_identity(path):
    """Resolve the actual local volume GUID, including mounted folders.

    Win32 APIs: GetVolumePathNameW and GetVolumeNameForVolumeMountPointW.
    An unavailable or changed identity never permits borrowing a prior proof.
    """
    try:
        kernel = ctypes.WinDLL('kernel32.dll', use_last_error=True, winmode=0x800)
        mount = kernel.GetVolumePathNameW
        name = kernel.GetVolumeNameForVolumeMountPointW
        for function in (mount, name):
            function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
            function.restype = ctypes.c_int
        mount_path = ctypes.create_unicode_buffer(32768)
        guid = ctypes.create_unicode_buffer(64)
        if (not mount(str(path), mount_path, len(mount_path)) or not mount_path.value.endswith('\\')
                or not name(mount_path.value, guid, len(guid))
                or not re.fullmatch(r'\\\\\?\\Volume\{[0-9a-fA-F-]{36}\}\\', guid.value)):
            raise OSError('volume_identity_unavailable')
        return guid.value.casefold()
    except (AttributeError, OSError):
        raise OSError('volume_identity_unavailable') from None


def _volume_data(raw):
    if not isinstance(raw, bytes) or len(raw) > 8192:
        raise ValueError('volume_response_quota')
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('volume_response_invalid')
    health, operations = data.get('volumeHealthStatus'), data.get('volumeOperationalStatus')
    if (not isinstance(health, str) or not 0 < len(health) <= 128
            or not isinstance(operations, list) or not 1 <= len(operations) <= 16
            or any(not isinstance(v, str) or not 0 < len(v) <= 128 for v in operations)):
        raise ValueError('volume_response_invalid')
    return dict(volumeHealthStatus=health, volumeOperationalStatus=operations)


class TaskResourceMonitor:
    def __init__(self, root, *, clock=time.monotonic):
        self.requested_root = Path(root).absolute()
        self.root = self.requested_root.resolve(strict=True)
        self.clock, self.system = clock, platform.system()
        self.task_id = uuid.uuid4().hex
        self._lock, self._sample_lock = threading.Lock(), threading.Lock()
        self._worker = self._process = self._result = None
        self._closed = self._initialized = self._identity_changed = False
        self._identity = self._last_launch = self._measurement = self._failure = None
        self._last_clock = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @staticmethod
    def _error(snapshot, component, kind):
        snapshot.setdefault('collectionError', kind)
        snapshot.setdefault('collectionErrors', []).append(dict(component=component, errorType=kind))

    def _check_identity(self):
        if self.requested_root.resolve(strict=True) != self.root:
            self._identity_changed = True
            raise OSError('volume_path_changed')
        identity = windows_volume_identity(self.root)
        if self._identity is None:
            self._identity = identity
        elif self._identity != identity:
            self._identity_changed = True
        if self._identity_changed:
            raise OSError('volume_identity_changed')
        return identity

    def _probe(self, identity):
        process = None
        result = dict(identity=identity)
        try:
            with self._lock:
                if self._closed:
                    return
                process = subprocess.Popen(
                    ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', resource_guard.WINDOWS_VOLUME_COMMAND],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    env=os.environ | {'SPHERE_RESOURCE_GUARD_PATH': str(self.root)})
                self._process = process
            try:
                stdout, _ = process.communicate(timeout=PROBE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=2)
                raise
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, 'volume_probe')
            result['data'] = _volume_data(stdout)
        except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as error:
            result['errorType'] = type(error).__name__
        finally:
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.SubprocessError):
                    result['errorType'] = 'VolumeProbeReapUnconfirmed'
            if process is not None and process.poll() is not None:
                for stream in (getattr(process, 'stdout', None), getattr(process, 'stderr', None)):
                    if stream is not None:
                        stream.close()
            result.update(completed_at=self.clock(), observed_at=utc_now())
            with self._lock:
                if process is None or process.poll() is not None:
                    self._process = None
                self._result = result

    def _launch(self, now, identity):
        with self._lock:
            if self._closed:
                raise RuntimeError('resource_monitor_closed')
            if self._worker is not None and self._worker.is_alive():
                return
            if self._process is not None:
                raise RuntimeError('volume_probe_reap_unconfirmed')
            self._last_launch = now
            self._worker = threading.Thread(target=self._probe, args=(identity,),
                                            name='sphere-task-volume-probe', daemon=True)
            self._worker.start()

    def _harvest(self):
        with self._lock:
            result, self._result = self._result, None
        if result is None:
            return False
        if (result.get('identity') != self._identity or self._identity_changed
                or not math.isfinite(result.get('completed_at', float('nan')))):
            self._measurement = None
            self._failure = dict(errorType='VolumeIdentityChanged')
        elif 'data' in result:
            # A newly measured warning replaces, rather than competes with,
            # an older healthy result. It cannot be hidden by the cache.
            self._measurement, self._failure = result, None
        else:
            self._failure = result
        return True

    def sample(self):
        with self._sample_lock:
            if self._closed:
                raise RuntimeError('resource_monitor_closed')
            now = self.clock()
            if (type(now) not in (int, float) or not math.isfinite(now)
                    or self._last_clock is not None and now < self._last_clock):
                raise RuntimeError('resource_monitor_clock_regressed')
            self._last_clock = now
            if self.system != 'Windows':
                # Linux retains its own fresh /proc semantics, with no Windows
                # subprocess, volume cache or commit comparison.
                snapshot = resource_guard.collect(self.root)
                snapshot.update(resourceMonitorTask=self.task_id, volumeProofScope='not_windows')
                return snapshot
            snapshot = dict(observedAt=utc_now(), system='Windows', deviceCommandsSent=False,
                            mutationsPerformed=False, resourceMonitorTask=self.task_id,
                            volumeProofScope='task_and_volume', volumeProofMaxAgeMs=30000)
            identity = None
            try:
                identity = self._check_identity()
                snapshot['volumeIdentity'] = identity
            except OSError as error:
                self._measurement = None
                self._error(snapshot, 'volume_identity', 'VolumeIdentityChanged' if self._identity_changed
                            else type(error).__name__)
            fresh = self._harvest()
            if identity is not None:
                if not self._initialized:
                    self._launch(now, identity)
                    # Only admission waits for a fresh full probe. Ongoing
                    # queries never wait for CIM/PowerShell or spawn per frame.
                    self._worker.join(PROBE_TIMEOUT_SECONDS + 3)
                    fresh = self._harvest()
                    self._initialized = True
                elif self._last_launch is None or now - self._last_launch >= PROBE_INTERVAL_SECONDS:
                    self._launch(now, identity)
                # Detect a mount change during the admission/probe hand-off.
                try:
                    self._check_identity()
                except OSError:
                    identity = None
                    self._measurement = None
                    self._error(snapshot, 'volume_identity', 'VolumeIdentityChanged')
            now = self.clock()
            measurement = self._measurement
            if measurement is not None and identity is not None:
                age = now - measurement['completed_at']
                snapshot['volumeProofAgeMs'] = age * 1000
                if 0 <= age <= PROOF_MAX_AGE_SECONDS:
                    data = measurement['data']
                    healthy = data['volumeHealthStatus'] == 'Healthy' and data['volumeOperationalStatus'] == ['OK']
                    # Unhealthy measurements remain explicit refusals. A
                    # failed refresh can reuse only a still-healthy proof.
                    if healthy or self._failure is None:
                        snapshot.update(volumeHealthStatus=data['volumeHealthStatus'],
                                        volumeOperationalStatus=list(data['volumeOperationalStatus']),
                                        volumeObservedAt=measurement['observed_at'],
                                        volumeMeasurement='fresh' if fresh else 'task_cache')
                    else:
                        snapshot['lastVolumeHealthStatus'] = data['volumeHealthStatus']
            if self._failure is not None:
                self._error(snapshot, 'volume_probe', self._failure['errorType'])
            with self._lock:
                snapshot['volumeProbeState'] = 'running' if self._worker is not None and self._worker.is_alive() else 'idle'
            # Do not copy a previous snapshot: both native memory and disk are
            # obtained independently even while a volume refresh is pending.
            try:
                snapshot['freeDiskBytes'] = shutil.disk_usage(self.root).free
                snapshot['diskObservedAt'] = utc_now()
            except OSError as error:
                self._error(snapshot, 'disk', type(error).__name__)
            try:
                snapshot.update(resource_guard.windows_memory())
                snapshot.update(memoryMeasurement='GetPerformanceInfo', memoryObservedAt=utc_now())
            except (OSError, ValueError) as error:
                self._error(snapshot, 'memory', type(error).__name__)
            snapshot['collectionCompletedAt'] = utc_now()
            if now < self._last_clock:
                raise RuntimeError('resource_monitor_clock_regressed')
            self._last_clock = now
            if self._closed:
                raise RuntimeError('resource_monitor_closed')
            return snapshot

    def close(self):
        with self._lock:
            self._closed = True
            process, worker = self._process, self._worker
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
        if worker is not None and worker is not threading.current_thread():
            worker.join(3)
        with self._lock:
            if ((worker is not None and worker.is_alive())
                    or self._process is not None and self._process.poll() is None):
                raise RuntimeError('volume_probe_close_unconfirmed')
