"""Bounded local walk summaries, after input closure; no pixels, keys or commands."""
from __future__ import annotations

import hashlib
import json
import math
import re

ID = re.compile(r'[0-9a-f]{32}')
CODE = re.compile(r'[a-z0-9_]{1,100}')


def store_walk_report(job, body):
    fields = {'schema', 'id', 'clip', 'release', 'stopReason', 'inputFailure',
              'stopFrameAgeMs', 'stopFrameSequence', 'executionQualified',
              'inputSummary', 'stages', 'observations'}
    if (type(body) is not dict or not fields <= body.keys() or not body.keys() <= fields|{'startMode'}
            or body['schema'] != 'sphere-walk-summary-v1'
            or body.get('startMode','beginning') not in {'beginning','recognized_route'}):
        raise ValueError('walk_report_schema')
    if any(type(body[k]) is not str or not ID.fullmatch(body[k]) for k in ['id', 'clip']):
        raise ValueError('walk_report_identity')
    if body['executionQualified'] is not False or body['release'] not in {'closed', 'unknown'}:
        raise ValueError('walk_report_qualification')

    def code(v):
        return type(v) is str and CODE.fullmatch(v)

    def number(v, *, nullable=False):
        return v is None and nullable or type(v) in {int, float} and math.isfinite(v) and 0 <= v <= 1e12

    if (not code(body['stopReason']) or body['inputFailure'] is not None and not code(body['inputFailure'])
            or not number(body['stopFrameAgeMs'], nullable=True) or not number(body['stopFrameSequence'])):
        raise ValueError('walk_report_stop')
    counts = body['inputSummary']
    if (type(counts) is not dict or set(counts) != {'submitted', 'applied', 'events'}
            or any(type(v) is not int or not 0 <= v <= 4096 for v in counts.values())):
        raise ValueError('walk_report_input_summary')
    stages = body['stages']
    if type(stages) is not list or len(stages) > 256:
        raise ValueError('walk_report_stages')
    allowed = {'stage', 'elapsedMs', 'durationMs', 'sequence', 'ageMs', 'reason'}
    for row in stages:
        if (type(row) is not dict or not {'stage', 'elapsedMs'} <= row.keys() or not row.keys() <= allowed
                or any(not code(v) if k in {'stage', 'reason'} else not number(v) for k, v in row.items())):
            raise ValueError('walk_report_stage')
    observations = body['observations']
    if type(observations) is not list or len(observations) > 1200:
        raise ValueError('walk_report_observations')
    required = {'elapsedMs', 'sequence', 'ageMs', 'computeMs', 'state', 'reason', 'poseState', 'inliers', 'progress'}
    allowed = required | {'segment', 'medianErrorPx', 'crossTrackUnits'}
    for row in observations:
        if (type(row) is not dict or not required <= row.keys() or not row.keys() <= allowed
                or any(not code(v) if k in {'state', 'reason', 'poseState'} else not number(v, nullable=k in {'progress', 'segment', 'medianErrorPx', 'crossTrackUnits'})
                       for k, v in row.items())):
            raise ValueError('walk_report_observation')
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > 512 * 1024:
        raise ValueError('walk_report_quota')
    folder = job / 'walk-reports'
    if folder.is_symlink():
        raise ValueError('walk_report_path')
    folder.mkdir(exist_ok=True)
    path = folder / (body['id'] + '.json')
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            raise ValueError('walk_report_conflict')
        state = 'existing'
    else:
        if len(list(folder.iterdir())) >= 64:
            raise ValueError('walk_report_retention_quota')
        with path.open('xb') as file:
            file.write(raw)
        state = 'saved'
    return {'state': state, 'sha256': hashlib.sha256(raw).hexdigest(), 'physicalActions': 0}
