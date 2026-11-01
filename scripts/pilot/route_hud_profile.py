"""Source-bound HUD speed references and a small fixed-font live reader.

This preset observes the Black Russia speed display. It does not recover pedal
presses, metric world positions, collision clearance or navigation authority.
Unknown glyphs and source gaps stay unknown; old OCR acceptance is unchanged.
"""
from __future__ import annotations

import bisect
import functools
import hashlib
import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

PROFILE = 'black_russia_scooter_v1'
BANK_SHA256 = '07bf4627ef92b16e8a016dd7ffc806d979c2797db8fa381a206d54d9f7a56bac'
BANK_PATH = Path(__file__).with_name('black_russia_speed_font_v1.json')
MAX_GAP_TICKS = 18000
MAX_ROWS = 36000
HEX = re.compile(r'^[0-9a-f]{64}$')


def _sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('speed_reference_regular_file')
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _json(path, maximum):
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= maximum:
        raise ValueError('speed_reference_json_quota')
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError('speed_reference_json')
    return value


@functools.lru_cache(maxsize=1)
def _bank():
    import numpy as np
    if _sha(BANK_PATH) != BANK_SHA256:
        raise ValueError('speed_font_changed')
    raw = _json(BANK_PATH, 65536)
    if raw.get('schema') != 'sphere-black-russia-speed-font-v1' or raw.get('hudProfile') != PROFILE:
        raise ValueError('speed_font_schema')
    rows = raw.get('templates')
    if not isinstance(rows, list) or not 10 <= len(rows) <= 160:
        raise ValueError('speed_font_quota')
    labels, masks = [], []
    for row in rows:
        if row.get('digit') not in '0123456789' or len(row.get('bits', '')) != 160:
            raise ValueError('speed_font_glyph')
        masks.append(np.unpackbits(np.frombuffer(bytes.fromhex(row['bits']), dtype=np.uint8), bitorder='big').astype(bool))
        labels.append(int(row['digit']))
    return np.asarray(labels), np.asarray(masks)


def _read_image(image):
    """Read a BGR 960x540 image already decoded for localization."""
    import cv2 as cv
    import numpy as np
    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.shape != (540, 960, 3):
        return None, 0.0, 'unsupported_geometry'
    gray = cv.cvtColor(image[465:485, 460:500], cv.COLOR_BGR2GRAY)
    mask = np.uint8(gray >= 175) * 255
    count, _, stats, _ = cv.connectedComponentsWithStats(mask)
    parts = []
    for index in range(1, count):
        x, y, width, height, area = map(int, stats[index])
        if area >= 4 and height >= 6:
            # Clipped, merged or unusually tall text must not become a number.
            if y == 0 or y + height >= 20 or width > 20 or height > 18 or area > 220:
                return None, 0.0, 'glyph_bounds'
            parts.append((x, y, width, height))
    parts.sort()
    if not 1 <= len(parts) <= 3:
        return None, 0.0, 'glyph_count'
    labels, templates = _bank()
    text, quality = '', 1.0
    for x, y, width, height in parts:
        glyph = cv.resize(mask[y:y + height, x:x + width], (20, 32), interpolation=cv.INTER_NEAREST).reshape(-1) > 0
        intersection = np.count_nonzero(templates & glyph, axis=1)
        union = np.count_nonzero(templates | glyph, axis=1)
        scores = intersection / np.maximum(1, union)
        ranked = sorted(((float(scores[labels == digit].max()), digit) for digit in range(10)), reverse=True)
        best, second = ranked[:2]
        if best[0] < .8 or best[0] - second[0] < .08:
            return None, best[0] * 100, 'glyph_ambiguous'
        text += str(best[1])
        quality = min(quality, best[0])
    if len(text) > 1 and text[0] == '0' or int(text) > 350:
        return None, quality * 100, 'speed_range'
    return float(text), quality * 100, 'accepted'


def read_live_speed(image_bgr960x540, *, epoch, sequence, received_at, jpeg_sha256, max_seconds=.08):
    """Observe this exact decoded frame; never hold or synthesize a prior speed.

    The caller must independently check the frame epoch, age and JPEG/RGB binding
    before control. Timing is a local processing duration, not capture latency.
    """
    if (not isinstance(epoch, str) or not 1 <= len(epoch) <= 128
            or type(sequence) is not int or sequence < 0
            or type(received_at) not in (int, float) or not math.isfinite(received_at)
            or not isinstance(jpeg_sha256, str) or not HEX.fullmatch(jpeg_sha256)
            or type(max_seconds) not in (int, float) or not 0 < max_seconds <= .25):
        raise ValueError('speed_frame_binding')
    began = time.perf_counter()
    try:
        speed, confidence, status = _read_image(image_bgr960x540)
    except (ValueError, OSError, KeyError, TypeError):
        speed, confidence, status = None, 0.0, 'font_unavailable'
    elapsed = time.perf_counter() - began
    if elapsed > max_seconds:
        speed, confidence, status = None, 0.0, 'processing_deadline'
    return dict(speed_kmh=speed, confidence=confidence, status=status, epoch=epoch,
                sequence=sequence, received_at=received_at, jpeg_sha256=jpeg_sha256,
                latency_ms=elapsed * 1000, hudProfile=PROFILE, units='game_hud_kmh',
                font_sha256=BANK_SHA256, world_metric=False,
                confidence_kind='glyph_iou_percent_not_probability')


@dataclass(frozen=True)
class SpeedReference:
    ticks: tuple[int, ...]
    speeds: tuple[float | None, ...]
    receipt: dict

    def sample(self, ticks_90k):
        if type(ticks_90k) not in (int, float) or not math.isfinite(ticks_90k):
            return None
        index = bisect.bisect_left(self.ticks, ticks_90k)
        if index < len(self.ticks) and self.ticks[index] == ticks_90k:
            return self.speeds[index]
        if not 0 < index < len(self.ticks):
            return None
        a, b = self.ticks[index - 1:index + 1]
        va, vb = self.speeds[index - 1:index + 1]
        if va is None or vb is None or b - a > MAX_GAP_TICKS:
            return None
        return va + (vb - va) * (ticks_90k - a) / (b - a)

    def preview(self, ticks_90k, horizon_ticks=90000):
        """Minimum supported future display speed; unknown intervals refuse."""
        if type(horizon_ticks) is not int or not 0 <= horizon_ticks <= 450000:
            return None
        first, last = self.sample(ticks_90k), self.sample(ticks_90k + horizon_ticks)
        if first is None or last is None:
            return None
        left = bisect.bisect_right(self.ticks, ticks_90k)
        right = bisect.bisect_left(self.ticks, ticks_90k + horizon_ticks)
        values = self.speeds[left:right]
        if any(value is None for value in values):
            return None
        covered = [ticks_90k, *self.ticks[left:right], ticks_90k + horizon_ticks]
        if any(b - a > MAX_GAP_TICKS for a, b in zip(covered, covered[1:])):
            return None
        return min(first, last, *values)


def _eligible(capture):
    config = capture.manifest.get('config', {})
    profile = config.get('profile', {})
    return (isinstance(profile, dict) and profile.get('hudProfile') == PROFILE
            and profile.get('mode') == 'vehicle_buttons'
            and config.get('hud_hidden_declared') is False and capture.geometry == (1920, 1080))


def prepare_speed_reference(job, *, checkpoint=None, max_seconds=90):
    """Decode a declared recording once and atomically seal an exclusive profile."""
    import cv2 as cv

    from motor_worker.browser_teach import decoded_browser, validate_browser
    from scripts.pilot.atomic_json import write_json
    from scripts.pilot.route_cpu_runtime import initialize_route_cpu_runtime
    initialize_route_cpu_runtime()
    cv.setNumThreads(2)
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 90:
        raise ValueError('speed_reference_time_quota')
    job = Path(job).resolve(strict=True)
    if any(path.is_symlink() or not path.resolve(strict=True).is_relative_to(job)
           for path in (job, job / 'input')):
        raise ValueError('speed_reference_path')
    began = time.monotonic()
    def check():
        if checkpoint is not None:
            checkpoint()
        if (job / 'CANCEL').exists():
            raise InterruptedError('cancelled')
        if time.monotonic() - began > max_seconds:
            raise TimeoutError('speed_reference_time_quota')
    check()
    capture = validate_browser(job / 'input')
    if not _eligible(capture):
        return None
    _bank()
    folder = job / 'vehicle-speed-reference'
    if folder.exists():
        raise FileExistsError('speed_reference_existing_intent')
    before = {name: _sha(job / 'input' / name) for name in ('manifest.json', 'video.h264', 'frames.jsonl', 'inputs.jsonl', 'COMPLETE')}
    check()
    folder.mkdir()
    created = []
    try:
        rows = []
        for meta, frame in decoded_browser(capture):
            check()
            if len(rows) >= MAX_ROWS:
                raise ValueError('speed_reference_row_quota')
            rgb = frame.to_ndarray(format='rgb24')
            bgr = cv.cvtColor(cv.resize(rgb, (960, 540), interpolation=cv.INTER_AREA), cv.COLOR_RGB2BGR)
            # The bank is measured at this codec scale. Training used JPEG85;
            # the actual stream image is observed independently at runtime.
            _, encoded = cv.imencode('.jpg', bgr, [cv.IMWRITE_JPEG_QUALITY, 85])
            observed = cv.imdecode(encoded, cv.IMREAD_COLOR)
            speed, confidence, status = _read_image(observed)
            rows.append(dict(index=meta['index'], ticks_90k=meta['relative_ticks_90k'],
                             speed_kmh=speed, confidence=confidence, status=status))
        if before != {name: _sha(job / 'input' / name) for name in before}:
            raise ValueError('speed_reference_source_changed')
        check()
        profile = dict(schema='sphere-hud-speed-reference-v1', hudProfile=PROFILE,
                       source_manifest_sha256=before['manifest.json'], rows=rows)
        path = folder / 'profile.json'
        created.append(path)
        write_json(path, profile)
        receipt = dict(schema='sphere-hud-speed-reference-receipt-v1', hudProfile=PROFILE,
                       source_hashes=before, profile_sha256=_sha(path), font_sha256=BANK_SHA256,
                       units='game_hud_kmh', world_metric=False, source_modified=False,
                       selected_count=len(rows), accepted_count=sum(r['status'] == 'accepted' for r in rows),
                       max_gap_ticks_90k=MAX_GAP_TICKS, commands_observed=False,
                       execution_qualified=False, processing_seconds=time.monotonic() - began)
        receipt_path = folder / 'receipt.json'
        created.append(receipt_path)
        write_json(receipt_path, receipt)
        marker = folder / 'COMPLETE'
        created.append(marker)
        marker.write_text(_sha(receipt_path) + '\n', encoding='ascii')
        check()
        return receipt
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        folder.rmdir()
        raise


def load_speed_reference(job):
    """Validate full un-decimated observations once, before creating a follower."""
    from motor_worker.browser_teach import validate_browser
    job = Path(job).resolve(strict=True)
    folder = job / 'vehicle-speed-reference'
    if not folder.exists():
        return None
    if any(path.is_symlink() or not path.resolve(strict=True).is_relative_to(job)
           for path in (job, job / 'input', folder)):
        raise ValueError('speed_reference_path')
    receipt = _json(folder / 'receipt.json', 65536)
    marker = folder / 'COMPLETE'
    if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 66 or marker.read_text('ascii').strip() != _sha(folder / 'receipt.json'):
        raise ValueError('speed_reference_incomplete')
    if (receipt.get('schema') != 'sphere-hud-speed-reference-receipt-v1'
            or receipt.get('hudProfile') != PROFILE or receipt.get('font_sha256') != BANK_SHA256
            or receipt.get('max_gap_ticks_90k') != MAX_GAP_TICKS
            or receipt.get('units') != 'game_hud_kmh' or receipt.get('world_metric') is not False
            or receipt.get('source_modified') is not False or receipt.get('commands_observed') is not False
            or receipt.get('execution_qualified') is not False):
        raise ValueError('speed_reference_receipt')
    expected = receipt.get('source_hashes')
    if not isinstance(expected, dict) or set(expected) != {'manifest.json', 'video.h264', 'frames.jsonl', 'inputs.jsonl', 'COMPLETE'}:
        raise ValueError('speed_reference_source_binding')
    if any(_sha(job / 'input' / name) != value for name, value in expected.items()):
        raise ValueError('speed_reference_source_changed')
    capture = validate_browser(job / 'input')
    if not _eligible(capture) or len(capture.frames) > MAX_ROWS:
        raise ValueError('speed_reference_preset')
    path = folder / 'profile.json'
    profile = _json(path, 8 * 1024**2)
    if (_sha(path) != receipt.get('profile_sha256')
            or profile.get('schema') != 'sphere-hud-speed-reference-v1'
            or profile.get('source_manifest_sha256') != expected['manifest.json']
            or profile.get('hudProfile') != PROFILE):
        raise ValueError('speed_reference_profile_binding')
    rows = profile.get('rows')
    if (not isinstance(rows, list) or len(rows) != len(capture.frames)
            or type(receipt.get('selected_count')) is not int or receipt['selected_count'] != len(rows)):
        raise ValueError('speed_reference_rows')
    accepted = 0
    for frame, row in zip(capture.frames, rows):
        if (not isinstance(row, dict) or type(row.get('index')) is not int
                or type(row.get('ticks_90k')) is not int
                or row['index'] != frame['index'] or row['ticks_90k'] != frame['relative_ticks_90k']):
            raise ValueError('speed_reference_frame_binding')
        speed, confidence, status = row.get('speed_kmh'), row.get('confidence'), row.get('status')
        if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 100:
            raise ValueError('speed_reference_confidence')
        if status == 'accepted':
            if type(speed) not in (int, float) or not math.isfinite(speed) or not 0 <= speed <= 350 or confidence < 80:
                raise ValueError('speed_reference_value')
            accepted += 1
        elif speed is not None:
            raise ValueError('speed_reference_unknown_value')
    if type(receipt.get('accepted_count')) is not int or accepted != receipt['accepted_count']:
        raise ValueError('speed_reference_counts')
    if any(_sha(job / 'input' / name) != value for name, value in expected.items()):
        raise ValueError('speed_reference_source_changed')
    return SpeedReference(tuple(r['ticks_90k'] for r in rows), tuple(r['speed_kmh'] for r in rows), receipt)
