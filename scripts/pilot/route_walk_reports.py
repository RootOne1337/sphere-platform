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
    if (type(body) is not dict or not fields <= body.keys() or not body.keys() <= fields|{'startMode','camera','cameraInput'}
            or body['schema'] != 'sphere-walk-summary-v1'
            or body.get('startMode','beginning') not in {'beginning','recognized_route'}):
        raise ValueError('walk_report_schema')
    if any(type(body[k]) is not str or not ID.fullmatch(body[k]) for k in ['id', 'clip']):
        raise ValueError('walk_report_identity')
    if body['executionQualified'] is not False or body['release'] not in {'closed', 'unknown'}:
        raise ValueError('walk_report_qualification')
    camera=body.get('camera')
    if camera is not None:
        camera_fields={'gainRadiansPerShortSide','pulses','calibrationAttempts','terminal'}
        if (type(camera) is not dict or not camera_fields<=camera.keys()
                or not camera.keys()<=camera_fields|{'minimumFraction','quietResponses','feedback','mode','pitchGainRadiansPerShortSide'}
                or camera.get('mode','continuous_drag_v1')!='continuous_drag_v1'
                or type(camera['pulses']) is not int or not 0<=camera['pulses']<=120
                or type(camera['calibrationAttempts']) is not int or not 0<=camera['calibrationAttempts']<=3
                or camera['gainRadiansPerShortSide'] is not None and (
                    type(camera['gainRadiansPerShortSide']) not in {int,float}
                    or not math.isfinite(camera['gainRadiansPerShortSide']) or not .2<=abs(camera['gainRadiansPerShortSide'])<=200)
                or camera['terminal'] is not None and (type(camera['terminal']) is not str or not CODE.fullmatch(camera['terminal']))):
            raise ValueError('walk_report_camera')
        pitch_gain=camera.get('pitchGainRadiansPerShortSide')
        if pitch_gain is not None and (type(pitch_gain) not in {int,float} or not math.isfinite(pitch_gain) or not .2<=abs(pitch_gain)<=200):
            raise ValueError('walk_report_camera')
        if ('minimumFraction' in camera and (type(camera['minimumFraction']) not in {int,float}
                or not math.isfinite(camera['minimumFraction']) or not .001<=camera['minimumFraction']<=.06)
                or 'quietResponses' in camera and (type(camera['quietResponses']) is not int or not 0<=camera['quietResponses']<=3)):
            raise ValueError('walk_report_camera_feedback')
        feedback=camera.get('feedback',[])
        if type(feedback) is not list or len(feedback)>32:
            raise ValueError('walk_report_camera_feedback')
        for row in feedback:
            if (type(row) is not dict or set(row)-{'axis','pitchBefore','pitchAfter'}!={'sequence','fraction','turnRadians','yawBefore','yawAfter','afterUpMs'}
                    or row.get('axis','x') not in {'x','y'}
                    or type(row['sequence']) is not int or not 1<=row['sequence']<=1000000
                    or any(type(v) not in {int,float} or not math.isfinite(v) for k,v in row.items() if k!='axis')
                    or not 0<abs(row['fraction'])<=.060001 or not 0<=row['afterUpMs']<=10000
                    or any(abs(row[k])>math.pi for k in ('turnRadians','yawBefore','yawAfter','pitchBefore','pitchAfter') if k in row)):
                raise ValueError('walk_report_camera_feedback')
    if 'cameraInput' in body:
        camera_input=body['cameraInput']
        camera_input_fields={'strokesSubmitted','strokesApplied','lastDistancePx','lastDurationMs'}
        if (type(camera_input) is not dict or not camera_input_fields<=camera_input.keys() or not camera_input.keys()<=camera_input_fields|{'movesApplied'}
                or 'movesApplied' in camera_input and (type(camera_input['movesApplied']) is not int or not 0<=camera_input['movesApplied']<=4096)
                or any(type(camera_input[k]) is not int or not 0<=camera_input[k]<=4096 for k in ('strokesSubmitted','strokesApplied'))
                or any(camera_input[k] is not None and (type(camera_input[k]) not in {int,float}
                    or not math.isfinite(camera_input[k]) or not 0<=camera_input[k]<=1e6) for k in ('lastDistancePx','lastDurationMs'))):
            raise ValueError('walk_report_camera_input')

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
    allowed = required | {'segment', 'medianErrorPx', 'crossTrackUnits','poseReason','plannerReason','cameraYawRadians','cameraPitchRadians'}
    for row in observations:
        if (type(row) is not dict or not required <= row.keys() or not row.keys() <= allowed
                or any((v is not None and (type(v) not in {int,float} or not math.isfinite(v) or abs(v)>math.pi)) if k in {'cameraYawRadians','cameraPitchRadians'}
                       else not code(v) if k in {'state', 'reason', 'poseState','poseReason','plannerReason'} else not number(v, nullable=k in {'progress', 'segment', 'medianErrorPx', 'crossTrackUnits'})
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
