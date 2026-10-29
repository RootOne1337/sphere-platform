"""Keep the loopback route API available; never replay jobs or native input.

Run by a per-user Windows scheduled task, outside the lifetime of a tool shell.
Only start the fixed local API when its loopback port is unoccupied. An occupied
but unhealthy port is diagnosed, never killed. Existing sessions are never
resumed across an API restart.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT/'.local-pilot/route-service-watchdog'
PORT = 3342
ORIGIN = 'http://127.0.0.1:3015'


def probe():
    try:
        with urlopen(Request(f'http://127.0.0.1:{PORT}/health', headers={
                'Origin': ORIGIN, 'X-Sphere-Reconstruction': '1'}), timeout=2) as response:
            data = json.loads(response.read(4096))
            if response.status == 200 and isinstance(data,dict) and data.get('service') == 'sphere-reconstruction-v1' and data.get('one_active_job') is True:
                return 'healthy'
    except (OSError, ValueError, URLError):
        pass
    with socket.socket() as sock:
        sock.settimeout(.3)
        return 'occupied' if sock.connect_ex(('127.0.0.1', PORT)) == 0 else 'absent'


def can_start(state, owned_running, elapsed):
    return state == 'absent' and not owned_running and elapsed >= 10


def main():
    if os.name != 'nt':
        raise RuntimeError('windows_task_only')
    import msvcrt
    FOLDER.mkdir(parents=True, exist_ok=True)
    lock = (FOLDER/'instance.lock').open('a+b')
    lock.seek(0)
    if not lock.read(1):
        lock.write(b'1'); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        return
    logger = logging.getLogger('route-service-watchdog')
    logger.setLevel(logging.INFO)
    log = logging.handlers.RotatingFileHandler(FOLDER/'watchdog.log', maxBytes=1024**2, backupCount=2, encoding='utf-8')
    log.setFormatter(logging.Formatter('%(asctime)s %(message)s')); logger.addHandler(log)
    interpreter = ROOT/'.local-pilot/motor-worker-venv/Scripts/python.exe'
    if not interpreter.is_file():
        raise RuntimeError('route_interpreter_missing')
    child = None
    previous = None
    last_start = -float('inf')
    attempts = 0
    try:
        while True:
            if child is not None and child.poll() is not None:
                logger.warning('Owned API exited: code=%s', child.returncode)
                child = None
            state = probe()
            if state != previous:
                logger.info('Health: %s; owns_process=%s', state, child is not None)
                previous = state
            elapsed = time.monotonic() - last_start
            # Back off repeated startup failures; no tight process or log loop.
            if can_start(state, child is not None, elapsed) and elapsed >= min(60, 10 * max(1, attempts)):
                last_start = time.monotonic()
                attempts += 1
                try:
                    child = subprocess.Popen([str(interpreter), '-m', 'scripts.pilot.reconstruction_service'],
                        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    logger.info('Started fixed route API: launcher_pid=%s', child.pid)
                except OSError as error:
                    logger.warning('Start failed: %s', type(error).__name__)
            if state == 'healthy':
                attempts = 0
            time.sleep(3)
    finally:
        # An adopted process is never terminated; the watchdog is not an input
        # owner. Stopping the task does not issue any Android or API mutation.
        lock.close()


if __name__ == '__main__':
    main()
