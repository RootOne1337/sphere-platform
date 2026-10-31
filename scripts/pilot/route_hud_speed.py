"""Offline OCR for the explicitly selected Black Russia HUD preset.

The acceptance filter was tuned on 60 inspected frames and checked against 31
separately labelled frames from one recording. It reports game HUD units only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRESET = 'measured_black_russia_hud'


def accepted_speed(text: str, confidence: float):
    """Reject low-confidence, ambiguous and unsupported single-digit readings."""
    if len(text) != 2 or not text.isascii() or not text.isdigit():
        return None
    if text == '14' or not math.isfinite(confidence) or not 50 <= confidence <= 100:
        return None
    return int(text)


def parse_tsv(data: str):
    try:
        rows = list(csv.DictReader(data.splitlines(), delimiter='\t', strict=True))
        words = [row for row in rows if isinstance(row.get('text'), str) and row['text'].strip()]
        if len(words) != 1:
            return '', -1.0
        conf = float(words[0]['conf'])
        if not math.isfinite(conf) or not 0 <= conf <= 100:
            return '', -1.0
        return words[0]['text'].strip(), conf
    except (ValueError, TypeError, KeyError, csv.Error):
        return '', -1.0


def _sha256(path, check):
    digest = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            check()
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _initialize():
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    initialize_route_cpu_runtime()
    import cv2
    cv2.setNumThreads(2)


def _validate(path):
    from motor_worker.browser_teach import validate_browser
    return validate_browser(path)


def _decode(capture):
    from motor_worker.browser_teach import decoded_browser
    return decoded_browser(capture)


def _ocr(frame, tesseract, env, timeout):
    import cv2 as cv
    rgb = frame.to_ndarray(format='rgb24')
    crop = rgb[931:969, 920:1000]
    crop = cv.resize(crop, None, fx=3, fy=3, interpolation=cv.INTER_CUBIC)
    gray = cv.cvtColor(crop, cv.COLOR_RGB2GRAY)
    _, mask = cv.threshold(gray, 175, 255, cv.THRESH_BINARY)
    ok, png = cv.imencode('.png', mask)
    if not ok:
        raise RuntimeError('HUD image encoding failed')
    proc = subprocess.run([str(tesseract), 'stdin', 'stdout', '--psm', '7',
                           '-c', 'tessedit_char_whitelist=0123456789', 'tsv'],
                          input=png.tobytes(), capture_output=True, timeout=timeout, env=env)
    if proc.returncode:
        raise RuntimeError('Tesseract failed: ' + proc.stderr.decode(errors='replace')[:500])
    return parse_tsv(proc.stdout.decode(errors='replace'))


def run(capture_path, output_path, tesseract, step=3, checkpoint=None, max_seconds=90):
    """Create an exclusive CSV and receipt; checkpoint() may raise to cancel.

    Only every step-th source frame is OCRed. Unselected frames are unknown.
    Failed or cancelled runs remove only files they themselves created.
    """
    if type(step) is not int or not 1 <= step <= 30:
        raise ValueError('step must be an integer in 1..30')
    if (isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds) or not 0 < max_seconds <= 90):
        raise ValueError('max_seconds must be finite and in (0, 90]')
    if checkpoint is not None and not callable(checkpoint):
        raise ValueError('checkpoint must be callable')
    deadline = time.monotonic() + max_seconds

    def check():
        if checkpoint is not None:
            checkpoint()
        if time.monotonic() >= deadline:
            raise TimeoutError('HUD extraction time quota exceeded')

    executable = Path(tesseract)
    if executable.is_symlink() or not executable.is_file() or not stat.S_ISREG(executable.stat().st_mode) or not os.access(executable, os.X_OK):
        raise ValueError('tesseract must be an executable regular file')
    output = Path(output_path).absolute()
    receipt_path = Path(str(output) + '.receipt.json')
    source = Path(capture_path).resolve(strict=True)
    if output.resolve().is_relative_to(source) or receipt_path.resolve().is_relative_to(source):
        raise ValueError('output cannot be inside source capture')
    check()
    _initialize()
    check()
    capture = _validate(source)
    check()
    if capture.geometry != (1920, 1080):
        raise ValueError('preset requires 1920x1080 geometry')
    video_path, manifest_path = source / 'video.h264', source / 'manifest.json'
    video_hash = _sha256(video_path, check)
    manifest_hash = _sha256(manifest_path, check)
    source_hashes = {name: hashlib.sha256(data).hexdigest()
                     for name, data in capture.originals.items()}
    if any(_sha256(source / name, check) != digest for name, digest in source_hashes.items()):
        raise ValueError('capture metadata changed after validation')
    env = os.environ.copy()
    env['OMP_THREAD_LIMIT'] = '1'
    created = []
    try:
        csv_file = output.open('x', newline='', encoding='utf-8')
        created.append(output)
        with csv_file:
            # Reserve both names before doing work; never overwrite a receipt.
            receipt_file = receipt_path.open('x', encoding='utf-8')
            created.append(receipt_path)
            with receipt_file:
                writer = csv.writer(csv_file)
                writer.writerow(['frame_index', 'relative_ticks_90k', 'seconds', 'hud_kmh',
                                 'ocr_text', 'ocr_confidence', 'status'])
                selected = accepted = 0
                for meta, frame in _decode(capture):
                    check()
                    if meta['index'] % step:
                        continue
                    timeout = min(5.0, deadline - time.monotonic())
                    if timeout <= 0:
                        raise TimeoutError('HUD extraction time quota exceeded')
                    text, conf = _ocr(frame, executable, env, timeout)
                    check()
                    speed = accepted_speed(text, conf)
                    selected += 1
                    accepted += speed is not None
                    ticks = meta['relative_ticks_90k']
                    writer.writerow([meta['index'], ticks, f'{ticks / 90000:.6f}',
                                     '' if speed is None else speed, text, conf,
                                     'unknown' if speed is None else 'accepted'])
                csv_file.flush()
                if (_sha256(video_path, check) != video_hash or
                        any(_sha256(source / name, check) != digest
                            for name, digest in source_hashes.items())):
                    raise RuntimeError('source changed during HUD extraction')
                csv_hash = _sha256(output, check)
                receipt = {'preset': PRESET, 'source_manifest_sha256': manifest_hash,
                           'source_video_sha256': video_hash, 'output_csv_sha256': csv_hash,
                           'geometry': [1920, 1080], 'selected_count': selected,
                           'accepted_count': accepted, 'unknown_count': selected - accepted,
                           'sampling_step': step, 'unselected_frames': 'unknown',
                           'crop_formula': 'rgb[931:969, 920:1000]',
                           'source_modified': False, 'units': 'game_hud_kmh',
                           'world_metric': False}
                json.dump(receipt, receipt_file, indent=2, allow_nan=False)
                receipt_file.write('\n')
                check()
        return receipt
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('output', type=Path, help='new CSV file')
    parser.add_argument('--tesseract', required=True, type=Path)
    parser.add_argument('--step', type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(run(args.capture, args.output, args.tesseract, args.step), indent=2))


if __name__ == '__main__':
    main()
