"""Bind a verified sparse reconstruction to its inputs, independently of rendering.

This receipt is evidence for offline preparation only; it does not qualify a
route for driving, certify camera accuracy, or measure collision-free space.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from scripts.pilot.atomic_json import write_json

SCHEMA = 'sphere-sparse-scene-receipt-v1'
FILES = ('geometry.json', 'quality.json', 'input/manifest.json',
         'prepared/reconstruction-input.json', 'prepared/sparse/0/cameras.bin',
         'prepared/sparse/0/images.bin', 'prepared/sparse/0/points3D.bin')
OPTIONAL = ('prepared/sparse/0/rigs.bin', 'prepared/sparse/0/frames.bin')


def _sha(job: Path, name: str) -> str:
    path = job / name
    # Do not follow symlinks in any component, including parent directories.
    if not path.is_file() or any(part.is_symlink() for part in [path, *path.parents] if part != job.parent):
        raise ValueError('sparse_source_missing_or_symlink')
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _quality(job: Path) -> None:
    _sha(job, 'quality.json')
    if (job / 'quality.json').stat().st_size > 65536:
        raise ValueError('sparse_quality_gate_failed')
    quality = json.loads((job / 'quality.json').read_text('utf-8'))
    if (type(quality.get('registered')) is not int or quality['registered'] < 10
            or type(quality.get('selected')) is not int or quality['selected'] < quality['registered']
            or quality['registered'] / quality['selected'] < .7
            or type(quality.get('points')) is not int or quality['points'] < 300
            or type(quality.get('mean_reprojection_px')) not in (int, float)
            or not math.isfinite(quality['mean_reprojection_px']) or not 0 <= quality['mean_reprojection_px'] <= 3
            or quality.get('conditioning', {}).get('passed') is not True
            or quality.get('intrinsics_condition', {}).get('passed') is not True):
        raise ValueError('sparse_quality_gate_failed')


def create_sparse_receipt(job: Path) -> dict:
    job = Path(job)
    if (job / 'sparse-receipt.json').exists():
        raise ValueError('sparse_receipt_already_exists')
    _quality(job)
    names = [*FILES, *(name for name in OPTIONAL if (job / name).exists())]
    hashes = {name: _sha(job, name) for name in names}
    provenance = json.loads((job / 'prepared/reconstruction-input.json').read_text('utf-8'))
    geometry = json.loads((job / 'geometry.json').read_text('utf-8'))
    if (provenance.get('source_manifest_sha256') != hashes['input/manifest.json']
            or geometry.get('source_manifest_sha256') != hashes['input/manifest.json']):
        raise ValueError('sparse_capture_binding_changed')
    receipt = dict(schema=SCHEMA, files=hashes, camera_trace_only=True,
                   navigation_qualified=False, execution_qualified=False)
    write_json(job / 'sparse-receipt.json', receipt)
    return receipt


def verify_sparse_receipt(job: Path) -> dict:
    job = Path(job)
    receipt_path = job / 'sparse-receipt.json'
    if receipt_path.is_symlink() or not receipt_path.is_file() or receipt_path.stat().st_size > 65536:
        raise ValueError('sparse_receipt_invalid')
    receipt = json.loads(receipt_path.read_text('utf-8'))
    files = receipt.get('files')
    if (receipt.get('schema') != SCHEMA or receipt.get('camera_trace_only') is not True
            or receipt.get('navigation_qualified') is not False or receipt.get('execution_qualified') is not False
            or not isinstance(files, dict) or not set(FILES) <= set(files)
            or set(files) - set(FILES) - set(OPTIONAL)):
        raise ValueError('sparse_receipt_invalid')
    for name, expected in files.items():
        if not isinstance(expected, str) or len(expected) != 64 or _sha(job, name) != expected:
            raise ValueError('sparse_source_changed')
    # An optional binary added later also changes the reconstruction on disk.
    if any((job / name).exists() != (name in files) for name in OPTIONAL):
        raise ValueError('sparse_source_changed')
    _quality(job)
    return receipt
