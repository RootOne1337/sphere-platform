"""Offline paired overlay sensitivity probe. No Android/network/input executor.

The explicitly selected local adapter must reset history and RNG for EVERY
request using --audit-seed. Repeated raw controls check that promise, but do not
attest adapter internals. A directional response is not navigation acceptance.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import statistics
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from motor_worker.policy import (
    ActionChunk,
    GamepadState,
    KeyboardMouseState,
    PolicyFrame,
    PolicyRequest,
)
from motor_worker.process_policy import ADAPTERS, ProcessPolicy, ProcessPolicyConfig
from scripts.pilot.resource_guard import collect, evaluate

VARIANTS = ('raw', 'left', 'straight', 'right', 'raw_repeat')


def overlay(rgb: bytes, size: int, variant: str) -> bytes:
    """Draw at the model's input size, never overwrite a recorded source image."""
    if (type(size) is not int or size not in (192, 256) or type(rgb) is not bytes
            or len(rgb) != size * size * 3 or variant not in VARIANTS):
        raise ValueError('invalid_overlay_probe_input')
    if variant in ('raw', 'raw_repeat'):
        return rgb
    import cv2
    import numpy as np

    image = np.frombuffer(rgb, np.uint8).reshape(size, size, 3).copy()
    target_x = {'left': .22, 'straight': .5, 'right': .78}[variant]
    path = np.array([[size * .5, size * .94], [size * .5, size * .78],
                     [size * target_x, size * .48]], dtype=np.int32)
    cv2.polylines(image, [path], False, (0, 255, 220), max(3, round(size / 48)), cv2.LINE_AA)
    return image.tobytes()


def steering(state) -> dict:
    if isinstance(state, GamepadState):
        return dict(lateral=state.left[0], forward=state.left[1], camera=state.right[0])
    return dict(lateral=int('d' in state.keys) - int('a' in state.keys),
                forward=int('w' in state.keys) - int('s' in state.keys), camera=state.mouse_delta_x)


def window_steering(chunk: dict, horizon_ms: int = 200) -> dict:
    """Time-weight the returned states only. Never invent a hold after the chunk.

    P2P returns one 50 ms state: that covers 25% of a 200 ms decision window.
    This statistic cannot assert how the remaining 150 ms would be controlled.
    """
    if type(horizon_ms) is not int or not 1 <= horizon_ms <= 2000:
        raise ValueError('invalid_overlay_horizon')
    states = tuple(GamepadState(tuple(s['left']), tuple(s['right']), tuple(s['buttons']))
                   if set(s) == {'left', 'right', 'buttons'} else
                   KeyboardMouseState(tuple(s['keys']), tuple(s['mouse_buttons']), s['mouse_delta_x'], s['mouse_delta_y'])
                   for s in chunk['states'])
    validated = ActionChunk(states, chunk['ticks_per_second'])
    duration = min(horizon_ms / 1000, len(states) / validated.ticks_per_second)
    totals = dict(lateral=0., forward=0., camera=0.)
    for index, state in enumerate(states):
        weight = max(0., min(duration, (index + 1) / validated.ticks_per_second)
                     - index / validated.ticks_per_second)
        for key, value in steering(state).items():
            totals[key] += weight * value
    return dict(horizonMs=horizon_ms, coveredMs=duration * 1000,
                meanOverCoveredInterval={key: value / duration for key, value in totals.items()},
                tailPolicy='UNSPECIFIED_NO_SYNTHETIC_HOLD')


def summarize(rows: list[dict]) -> dict:
    grouped = {}
    for row in rows:
        key = (row['image'], row['seed'])
        pair = grouped.setdefault(key, {})
        if row['variant'] in pair:
            raise ValueError('duplicate_overlay_variant')
        pair[row['variant']] = row
    if not grouped or any(set(group) != set(VARIANTS) for group in grouped.values()):
        raise ValueError('incomplete_overlay_pairs')
    pairs = []
    for (image, seed), group in grouped.items():
        deterministic = group['raw']['chunk'] == group['raw_repeat']['chunk']
        left, right = (group[k]['steering'] for k in ('left', 'right'))
        windows = [window_steering(group[k]['chunk']) for k in ('left', 'right')]
        means = [window['meanOverCoveredInterval'] for window in windows]
        pairs.append(dict(image=image, seed=seed, repeatRawIdentical=deterministic,
                          rightMinusLeftLateral=right['lateral'] - left['lateral'],
                          rightMinusLeftCamera=right['camera'] - left['camera'],
                          windowCoveredMs=min(w['coveredMs'] for w in windows),
                          windowRightMinusLeftLateral=means[1]['lateral'] - means[0]['lateral'],
                          windowRightMinusLeftCamera=means[1]['camera'] - means[0]['camera']))
    return dict(pairs=pairs, repeatRawIdentical=all(x['repeatRawIdentical'] for x in pairs),
                positiveLateralPairs=sum(x['rightMinusLeftLateral'] > 0 for x in pairs),
                positiveCameraPairs=sum(x['rightMinusLeftCamera'] > 0 for x in pairs),
                positiveWindowLateralPairs=sum(x['windowRightMinusLeftLateral'] > 0 for x in pairs),
                positiveWindowCameraPairs=sum(x['windowRightMinusLeftCamera'] > 0 for x in pairs),
                totalPairs=len(pairs), directionalNavigationAccepted=False,
                inferenceWallMedianMs=statistics.median(x['wallMs'] for x in rows))


async def run(args) -> dict:
    import cv2

    if (len(args.image) > 6 or len(args.seeds) > 5 or len(set(args.seeds)) != len(args.seeds)
            or any(not 0 <= seed < 2**31 for seed in args.seeds)):
        raise ValueError('overlay_probe_budget')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    # This does not relax the existing heavy-work admission threshold.
    before = collect(Path.cwd())
    if evaluate(before, min_ram_gib=12):
        raise ValueError('overlay_resource_guard')
    sources = []
    for index, name in enumerate(args.image):
        path = Path(name).resolve(strict=True)
        if path.is_symlink() or path.stat().st_size > 32 * 1024**2:
            raise ValueError('overlay_image_bound')
        image = cv2.imread(str(path))
        if image is None:
            raise ValueError('overlay_image_decode')
        rgb = cv2.cvtColor(cv2.resize(image, (args.size, args.size), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB).tobytes()
        source = dict(image=index, source=path.name, sourceSha256=hashlib.sha256(path.read_bytes()).hexdigest(), variants={})
        for variant in VARIANTS:
            data = overlay(rgb, args.size, variant)
            source['variants'][variant] = data
            # Inspectable exact probe input; the raw source file remains untouched.
            import numpy as np
            rendered = np.frombuffer(data, np.uint8).reshape(args.size, args.size, 3)
            cv2.imwrite(str(output / f'{index}-{variant}.png'), cv2.cvtColor(rendered, cv2.COLOR_RGB2BGR))
        sources.append(source)
    report = dict(schemaVersion=1, kind='OFFLINE_OVERLAY_SENSITIVITY_NOT_NAVIGATION',
                  adapter=args.adapter, adapterScriptSha256=hashlib.sha256(Path(args.script).read_bytes()).hexdigest(),
                  resourcesBefore=before, sources=[{k: v for k, v in s.items() if k != 'variants'} for s in sources],
                  size=args.size, rows=[], providers=[], physicalActions=0, modelGoalConditioning=False,
                  lineDerivedFromVerifiedRoute=False, error=None)
    try:
        for seed in args.seeds:
            provider = ProcessPolicy(ProcessPolicyConfig(Path(args.python).resolve(strict=True),
                Path(args.script).resolve(strict=True), args.adapter, ('--stdio', '--audit-seed', str(seed))))
            try:
                await provider.start()
                report.setdefault('resourcesAfterWarmup', []).append(collect(Path.cwd()))
                if evaluate(report['resourcesAfterWarmup'][-1], min_ram_gib=12):
                    raise ValueError('overlay_post_warmup_guard')
                sequence = 0
                for source in sources:
                    for variant in VARIANTS:
                        sequence += 1
                        now = time.perf_counter()
                        frame = PolicyFrame(str(uuid.uuid4()), sequence, now, args.size, args.size, source['variants'][variant])
                        result = await provider.predict(PolicyRequest(sequence, frame, now + 1.95))
                        report['rows'].append(dict(image=source['image'], seed=seed, variant=variant,
                            inputRgbSha256=hashlib.sha256(frame.rgb24).hexdigest(),
                            wallMs=(time.perf_counter() - now) * 1000, chunk=asdict(result.chunk),
                            steering=steering(result.chunk.states[0])))
            finally:
                await provider.close()
                report['providers'].append(provider.report())
    except Exception as error:
        report['error'] = type(error).__name__
        report['errorCode'] = str(error) if type(error) is ValueError and str(error) in {
            'overlay_post_warmup_guard', 'overlay_resource_guard',
        } else None
    finally:
        if report['error'] is None:
            report['summary'] = summarize(report['rows'])
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True)
    parser.add_argument('--script', required=True)
    parser.add_argument('--adapter', choices=sorted(ADAPTERS), required=True)
    parser.add_argument('--image', action='append', required=True)
    parser.add_argument('--size', choices=(192, 256), type=int, required=True)
    parser.add_argument('--seeds', nargs='+', type=int, default=[17, 29, 43])
    parser.add_argument('--output', required=True)
    report = asyncio.run(run(parser.parse_args()))
    print(json.dumps({k: report.get(k) for k in ('kind', 'error', 'summary', 'physicalActions')}))
    return int(report['error'] is not None)


if __name__ == '__main__':
    raise SystemExit(main())
