"""Bounded, offline job-owned telemetry for an explicitly declared scooter HUD."""
from __future__ import annotations

import argparse
from collections import OrderedDict
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from motor_worker.browser_teach import validate_browser
from scripts.pilot.route_hud_speed import accepted_speed

PYTHON = ROOT / '.local-pilot/motor-worker-venv/Scripts/python.exe'
TESSERACT = Path('C:/Program Files/Tesseract-OCR/tesseract.exe')
PROFILE = 'black_russia_scooter_v1'
PRESET = 'measured_black_russia_hud'
MAX_ROWS = 12001
MAX_CSV = 4 * 1024 * 1024
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()


def _digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('regular_file_required')
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def _json(path, maximum=65536):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('json_invalid')
    value = json.loads(path.read_bytes())
    if type(value) is not dict:
        raise ValueError('json_invalid')
    return value


def _exclusive_json(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, separators=(',', ':'))
        f.flush()
        os.fsync(f.fileno())


def _state(folder, phase):
    path = folder / 'state.json'
    temp = folder / ('state.' + uuid.uuid4().hex + '.tmp')
    try:
        _exclusive_json(temp, {'phase': phase})
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _manifest_sha(capture):
    return hashlib.sha256(capture.originals['manifest.json']).hexdigest()


def _eligible(capture):
    config = capture.manifest.get('config', {})
    profile = config.get('profile', {})
    return (type(profile) is dict and profile.get('hudProfile') == PROFILE
            and profile.get('mode') == 'vehicle_buttons'
            and config.get('hud_hidden_declared') is False
            and capture.geometry == (1920, 1080))


def start(job, capture):
    """Start an eligible job-owned child or return None. Never launches input."""
    job = Path(job).resolve(strict=True)
    if not hasattr(capture, 'manifest'):
        capture = validate_browser(Path(capture))
    if not _eligible(capture):
        return None
    bound = validate_browser(job / 'input')
    if _manifest_sha(bound) != _manifest_sha(capture):
        raise ValueError('hud_capture_binding')
    folder = job / 'telemetry'
    folder.mkdir(exist_ok=True)
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError('hud_workspace_invalid')
    # Existing artifacts belong to another invocation; never truncate or replace.
    if any((folder / name).exists() for name in ('intent.json', 'state.json', 'speed.csv', 'speed.csv.receipt.json')):
        raise FileExistsError('hud_workspace_already_exists')
    _exclusive_json(folder / 'intent.json', {'schema': 'route-hud-intent-v1',
                    'source_manifest_sha256': _manifest_sha(bound), 'preset': PRESET})
    try:
        _exclusive_json(folder / 'state.json', {'phase': 'pending'})
    except BaseException:
        (folder / 'intent.json').unlink(missing_ok=True)
        raise
    if any(path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK)
           for path in (PYTHON, TESSERACT)):
        _state(folder, 'unavailable')
        return None
    if (job / 'CANCEL').exists():
        _state(folder, 'cancelled')
        return None
    try:
        return subprocess.Popen([str(PYTHON), str(Path(__file__).resolve()), '--job', str(job)],
                                cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        _state(folder, 'unavailable')
        return None


def settle_child(job, *, cancelled=False):
    """A dead/terminated owned child must not leave an endless processing badge."""
    folder=Path(job)/'telemetry'
    try:
        if folder.is_symlink():return
        if _json(folder/'state.json').get('phase') in {'pending','running'}:
            _state(folder,'cancelled' if cancelled else 'failed')
    except (OSError,ValueError,TypeError):
        return


def _worker(job):
    from scripts.pilot.route_hud_speed import run
    job = Path(job).resolve(strict=True)
    folder = job / 'telemetry'
    start_time = time.monotonic()
    def checkpoint():
        if (job / 'CANCEL').exists() or (folder / 'CANCEL').exists():
            raise InterruptedError('cancelled')
        if time.monotonic() - start_time >= 90:
            raise TimeoutError('hud_timeout')
    try:
        intent = _json(folder / 'intent.json')
        capture = validate_browser(job / 'input')
        if (intent.get('schema') != 'route-hud-intent-v1' or intent.get('preset') != PRESET
                or intent.get('source_manifest_sha256') != _manifest_sha(capture)
                or not _eligible(capture)):
            raise ValueError('hud_capture_binding')
        checkpoint()
        _state(folder, 'running')
        remaining = 90 - (time.monotonic() - start_time)
        run(job / 'input', folder / 'speed.csv', TESSERACT, step=3,
            checkpoint=checkpoint, max_seconds=remaining)
        checkpoint()
        _state(folder, 'ready')
    except InterruptedError:
        _state(folder, 'cancelled')
    except Exception:
        _state(folder, 'failed')


def _samples(rows):
    # Every bucket containing unknown observations stays unknown. Time gaps
    # are explicitly flagged; this is a conservative overview, not resampling.
    size = max(1, math.ceil(len(rows) / 601))
    samples = []
    previous_ticks = None
    for pos in range(0, len(rows), size):
        bucket = rows[pos:pos + size]
        ticks = bucket[0][0]
        gap = previous_ticks is not None and ticks - previous_ticks > 18000
        for (a, _), (b, _) in zip(bucket, bucket[1:]):
            gap |= b - a > 18000
        samples.append({'ticks_90k': ticks,
                        'hud_kmh': None if gap or any(v is None for _, v in bucket) else bucket[0][1],
                        'gap_before': bool(gap)})
        previous_ticks = bucket[-1][0]
    return samples


def _read_status_uncached(job):
    """Return a bounded public summary; reject unbound or tampered artifacts."""
    job = Path(job)
    folder = job / 'telemetry'
    if not folder.exists():
        return None
    try:
        intent = _json(folder / 'intent.json')
        state = _json(folder / 'state.json')
        phase = state.get('phase')
        if phase not in {'pending', 'running', 'ready', 'failed', 'cancelled', 'unavailable'}:
            raise ValueError('hud_state')
        manifest_sha = _digest(job / 'input/manifest.json')
        if (intent.get('schema') != 'route-hud-intent-v1' or intent.get('preset') != PRESET
                or intent.get('source_manifest_sha256') != manifest_sha):
            raise ValueError('hud_binding')
        if phase != 'ready':
            return {'phase': phase}
        capture = validate_browser(job / 'input')
        if _manifest_sha(capture) != manifest_sha:
            raise ValueError('hud_manifest_changed')
        receipt = _json(folder / 'speed.csv.receipt.json')
        csv_path = folder / 'speed.csv'
        if csv_path.is_symlink() or not csv_path.is_file() or csv_path.stat().st_size > MAX_CSV:
            raise ValueError('hud_csv_size')
        if (receipt.get('preset') != PRESET or receipt.get('source_manifest_sha256') != manifest_sha
                or receipt.get('source_video_sha256') != _digest(job / 'input/video.h264')
                or receipt.get('output_csv_sha256') != _digest(csv_path)
                or receipt.get('geometry') != [1920, 1080] or capture.geometry != (1920, 1080)
                or receipt.get('sampling_step') != 3 or receipt.get('source_modified') is not False
                or receipt.get('units') != 'game_hud_kmh' or receipt.get('world_metric') is not False):
            raise ValueError('hud_receipt_binding')
        if any(type(receipt.get(key)) is not int or not 0 <= receipt[key] <= MAX_ROWS
               for key in ('selected_count', 'accepted_count', 'unknown_count')):
            raise ValueError('hud_receipt_counts')
        rows = []
        counts = {'accepted': 0, 'unknown': 0}
        with csv_path.open(newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f, strict=True)
            if reader.fieldnames != ['frame_index', 'relative_ticks_90k', 'seconds', 'hud_kmh', 'ocr_text', 'ocr_confidence', 'status']:
                raise ValueError('hud_csv_header')
            for row in reader:
                if len(rows) >= MAX_ROWS or None in row:
                    raise ValueError('hud_csv_quota')
                index, ticks = int(row['frame_index']), int(row['relative_ticks_90k'])
                if index != len(rows) * 3 or index >= len(capture.frames) or ticks != capture.frames[index]['relative_ticks_90k']:
                    raise ValueError('hud_frame_binding')
                conf = float(row['ocr_confidence'])
                value = accepted_speed(row['ocr_text'], conf)
                status = 'unknown' if value is None else 'accepted'
                if row['status'] != status or row['hud_kmh'] != ('' if value is None else str(value)):
                    raise ValueError('hud_csv_result')
                seconds = float(row['seconds'])
                if not math.isfinite(seconds) or abs(seconds - ticks / 90000) > 0.000001:
                    raise ValueError('hud_csv_time')
                counts[status] += 1
                rows.append((ticks, value))
        expected = (len(capture.frames) + 2) // 3
        if (len(rows) != expected or receipt.get('selected_count') != expected
                or receipt.get('accepted_count') != counts['accepted']
                or receipt.get('unknown_count') != counts['unknown']):
            raise ValueError('hud_counts')
        return {'phase': 'ready', 'accepted_count': counts['accepted'],
                'unknown_count': counts['unknown'], 'selected_count': len(rows),
                'units': 'game_hud_kmh', 'source_manifest_sha256': manifest_sha,
                'samples': _samples(rows)}
    except (OSError, ValueError, TypeError, KeyError, csv.Error, OverflowError):
        return {'phase': 'invalid'}


def _fingerprint(job):
    paths = ('telemetry/intent.json', 'telemetry/state.json', 'telemetry/speed.csv',
             'telemetry/speed.csv.receipt.json', 'input/manifest.json', 'input/frames.jsonl',
             'input/inputs.jsonl', 'input/video.h264', 'input/COMPLETE')
    result = []
    for name in paths:
        path = job / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('hud_fingerprint_file')
        st = path.stat()
        result.append((st.st_size, st.st_mtime_ns, st.st_ino))
    return tuple(result)


def read_status(job):
    """Cache validated display summaries only; never use for motor control."""
    job = Path(job).absolute()
    if any(path.is_symlink() for path in (job,job/'input',job/'telemetry')):
        return {'phase':'invalid'}
    try:
        # Pending states do not require CSV files and never expose samples.
        if _json(job / 'telemetry/state.json').get('phase') != 'ready':
            return _read_status_uncached(job)
        before = _fingerprint(job)
        key = str(job)
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached is not None and cached[0] == before:
                _CACHE.move_to_end(key)
                return copy.deepcopy(cached[1])
        result = _read_status_uncached(job)
        after = _fingerprint(job)
        if before != after:
            return {'phase': 'invalid'}
        if result is not None and result.get('phase') == 'ready':
            with _CACHE_LOCK:
                _CACHE[key] = (after, copy.deepcopy(result))
                _CACHE.move_to_end(key)
                while len(_CACHE) > 32:
                    _CACHE.popitem(last=False)
        return result
    except (OSError, ValueError, TypeError, KeyError):
        return None if not (job / 'telemetry').exists() else {'phase': 'invalid'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True, type=Path)
    args = parser.parse_args()
    _worker(args.job)


if __name__ == '__main__':
    main()
