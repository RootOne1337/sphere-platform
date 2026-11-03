"""Resolve fixed, source-bound native bundles for explicit route preparation.

An alternate display is not a runtime map. Only an admitted native bundle in
that alternate's own directory can be exported; no caller supplies a path.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.pilot.alternative_geometry import ID, alternative, list_alternatives

MODEL_FILES = frozenset(('cameras.bin', 'images.bin', 'points3D.bin', 'frames.bin', 'rigs.bin'))
SCHEMA = 'sphere-alternative-native-source-v1'


def cancel_marker(path):
    """Identity of an old parent fence; a later touch/replacement is new cancel."""
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024:
        raise ValueError('route_cancel_marker')
    stat = path.stat()
    return dict(sha256=_digest(path), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns,
                ctime_ns=stat.st_ctime_ns, inode=stat.st_ino)


def attempt_cancelled(job, folder, *, intent=None):
    """Fresh explicit alternatives preserve, but cannot inherit, an old fence."""
    if (folder/'CANCEL').exists():
        return True
    if intent is None:
        path = folder/'intent.json'
        intent = json.loads(path.read_bytes()) if path.is_file() else {}
    if intent.get('alternativeId') is None:
        return (job/'CANCEL').exists()  # Legacy semantics unchanged.
    policy = intent.get('cancellationPolicy')
    if not isinstance(policy, dict) or set(policy) != {'parentCancelAtIntent'}:
        return True
    return cancel_marker(job/'CANCEL') != policy['parentCancelAtIntent']


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _inside(job, path):
    if not path.resolve(strict=True).is_relative_to(job.resolve(strict=True)):
        raise ValueError('route_alternative_native_path')
    for item in (path, *path.parents):
        if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
            raise ValueError('route_alternative_native_path')
        if item == job:
            break


def resolve_alternative_source(job, identity, *, digest=_digest):
    """Validate an immutable alternate's geometry, source index and native bytes."""
    job = Path(job)
    if not isinstance(identity, str) or not ID.fullmatch(identity):
        raise ValueError('route_alternative_id')
    body, info = alternative(job, identity)
    base = job/'alternatives'/identity
    folder = base/'native'
    source = folder/'source.json'
    if not source.is_file():
        raise ValueError('route_alternative_native_missing')
    _inside(job, source)
    if not 0 < source.stat().st_size <= 16384:
        raise ValueError('route_alternative_native_quota')
    record = json.loads(source.read_bytes())
    geometry_sha = hashlib.sha256(body).hexdigest()
    if (not isinstance(record, dict) or record.get('schema') != SCHEMA or record.get('alternative_id') != identity
            or record.get('scope') != 'READ_ONLY_ROUTE_ASSETS'
            or record.get('execution_qualified') is not False
            or record.get('geometry_sha256') != geometry_sha
            or record.get('source_manifest_sha256') != digest(job/'input/manifest.json')
            or record.get('reconstruction_input_sha256') != digest(job/'prepared/reconstruction-input.json')):
        raise ValueError('route_alternative_native_binding')
    files = record.get('model_sha256')
    model = folder/'model'
    _inside(job, model)
    actual = list(model.iterdir())
    if (not isinstance(files, dict) or set(files) != MODEL_FILES
            or {path.name for path in actual} != MODEL_FILES
            or any(not path.is_file() for path in actual)):
        raise ValueError('route_alternative_native_layout')
    if sum(path.stat().st_size for path in actual) > 64*1024**2:
        raise ValueError('route_alternative_native_quota')
    for path in actual:
        _inside(job, path)
        if digest(path) != files[path.name]:
            raise ValueError('route_alternative_native_changed')
    evidence = record.get('evidence_sha256')
    if not isinstance(evidence, dict) or set(evidence) != {'assessment.json', 'producer-proof.json'}:
        raise ValueError('route_alternative_native_evidence')
    for name, expected in evidence.items():
        path = folder/name
        _inside(job, path)
        if not 0 < path.stat().st_size <= 65536 or digest(path) != expected:
            raise ValueError('route_alternative_native_evidence')
    assessment = json.loads((folder/'assessment.json').read_bytes())
    if (assessment.get('route_admissible') is not True or assessment.get('scene_admissible') is not True
            or assessment.get('registered') != info['cameras'] or assessment.get('points') != info['points']
            or assessment.get('source_coverage', {}).get('endpoints_observed') is not True
            or assessment.get('source_coverage', {}).get('all_intervals_observed') is not True):
        raise ValueError('route_alternative_geometry_not_admitted')
    binding = dict(schema='sphere-route-preparation-source-v1', kind='alternative',
        alternative_id=identity, runtime_family='reference_lk', geometry_sha256=geometry_sha,
        source_manifest_sha256=record['source_manifest_sha256'],
        reconstruction_input_sha256=record['reconstruction_input_sha256'],
        native_source_sha256=digest(source), model_sha256=files)
    return dict(geometry_path=base/'geometry.json', model_path=model, binding=binding, info=info)


def attempt_source(job, folder, *, digest=_digest):
    """An attempt stays bound to its selected source even if review selection changes."""
    intent = folder/'intent.json'
    if intent.is_file():
        _inside(job, intent)
        if not 0 < intent.stat().st_size <= 65536:
            raise ValueError('route_preparation_source_binding')
        record = json.loads(intent.read_bytes())
        identity = record.get('alternativeId')
        if identity is not None:
            selected = resolve_alternative_source(job, identity, digest=digest)
            if record.get('sourceBinding') != selected['binding']:
                raise ValueError('route_preparation_source_changed')
            return selected
        if 'sourceBinding' in record:
            raise ValueError('route_preparation_source_binding')
    return dict(geometry_path=job/'geometry.json', model_path=None, binding=None,
                info=dict(id=None))


def public_source(selected, *, digest=_digest):
    binding = selected['binding']
    return dict(alternativeId=binding['alternative_id'] if binding else None,
                geometry_sha256=binding['geometry_sha256'] if binding else digest(selected['geometry_path']),
                runtime_family='reference_lk' if binding else 'legacy_sparse')


def preparation_sources(job, *, digest=_digest):
    result = []
    for info in list_alternatives(job):
        try:
            selected = resolve_alternative_source(job, info['id'], digest=digest)
            result.append(dict(public_source(selected), cameras=info['cameras'], points=info['points']))
        except (OSError, ValueError, TypeError, KeyError):
            continue  # Display-only, missing or altered bundles are not preparable.
    return result
