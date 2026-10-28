"""Read-only, capability-scoped alternate reconstructions for a saved job."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,47}$')
MAX_BYTES = 16 * 1024 * 1024


def alternative(job: Path, identity: str):
    if not isinstance(identity, str) or not ID.fullmatch(identity):
        raise ValueError('alternative_geometry_id')
    root = job / 'alternatives'
    folder = root / identity
    metadata = folder / 'receipt.json'
    geometry = folder / 'geometry.json'
    manifest = job / 'input/manifest.json'
    for path in (root, folder, metadata, geometry, manifest, manifest.parent):
        if path.is_symlink() or not path.resolve(strict=True).is_relative_to(job.resolve(strict=True)):
            raise ValueError('alternative_geometry_path')
    if metadata.stat().st_size > 4096 or manifest.stat().st_size > 65536 or geometry.stat().st_size > MAX_BYTES:
        raise ValueError('alternative_geometry_quota')
    receipt = json.loads(metadata.read_text('utf-8'))
    if (not isinstance(receipt, dict) or receipt.get('schema') != 'sphere-alternative-geometry-v1'
            or receipt.get('id') != identity or receipt.get('scope') != 'DIAGNOSTIC_ONLY'
            or receipt.get('execution_qualified') is not False
            or receipt.get('source_manifest_sha256') != hashlib.sha256(manifest.read_bytes()).hexdigest()):
        raise ValueError('alternative_geometry_binding')
    body = geometry.read_bytes()
    if hashlib.sha256(body).hexdigest() != receipt.get('geometry_sha256'):
        raise ValueError('alternative_geometry_changed')
    parsed = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_geometry')))
    if (not isinstance(parsed, dict) or parsed.get('schema') != 'sphere-recovered-scene-v1'
            or parsed.get('source_manifest_sha256') != receipt['source_manifest_sha256']
            or parsed.get('execution_qualified') is not False
            or not isinstance(parsed.get('cameras'), list) or not 2 <= len(parsed['cameras']) <= 240
            or not isinstance(parsed.get('points'), list) or len(parsed['points']) > 60000):
        raise ValueError('alternative_geometry_invalid')
    return body, {'id': identity, 'cameras': len(parsed['cameras']), 'points': len(parsed['points']),
                  'scope': 'diagnostic', 'executionQualified': False}


def list_alternatives(job: Path):
    root = job / 'alternatives'
    if not root.exists():
        return []
    if root.is_symlink() or not root.resolve(strict=True).is_relative_to(job.resolve(strict=True)):
        raise ValueError('alternative_geometry_path')
    folders = sorted(root.iterdir(), key=lambda p: p.name)
    if len(folders) > 16:
        raise ValueError('alternative_geometry_quota')
    result = []
    for folder in folders:
        if not ID.fullmatch(folder.name):
            continue
        try:
            _, item = alternative(job, folder.name)
            result.append(item)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            # Damaged alternatives are never silently used as valid geometry.
            continue
    return result
