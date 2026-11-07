"""Scoped admission for bounded CPU route-camera preparation, not dense training.

The route path retains four GiB for the host and budgets its video validation/
decode copies separately. Gaussian/model training and all non-route jobs retain
the existing resource evaluator and its 85% Windows commit ceiling unchanged.
These helpers only inspect file metadata and supplied measurements.
"""
from __future__ import annotations

import math
import stat
from pathlib import Path

from scripts.pilot.resource_guard import evaluate

GIB = 2**30
MAX_VIDEO_BYTES = 2**31
KIND = 'route_reconstruction_cpu'


def _video_bytes(job):
    """Missing, unreadable, non-regular and symlink sources have unknown size."""
    job = Path(job)
    path = job / 'input/video.h264'
    try:
        for component in (path, path.parent, job):
            if component.is_symlink():
                return None
        metadata = path.stat()
        if stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= MAX_VIDEO_BYTES:
            return metadata.st_size
    except OSError:
        pass
    return None


def profile(job, *, route_only, uploading=False):
    """Return the route CPU budget, or None to preserve heavy-job admission.

    An explicit upload admission leaves six GiB available before source size is
    known. After upload, unknown/invalid size uses twelve GiB, never the upload
    allowance. A valid source uses quarter-GiB rounding of
    ``4 + 1.5 + 3 * compressed_video_GiB``, bounded to [6, 12] GiB.
    No Torch/model initialization is authorized or budgeted by this profile.
    """
    if type(route_only) is not bool or type(uploading) is not bool:
        raise ValueError('route_reconstruction_resource_scope')
    if not route_only:
        return None
    size = None if uploading else _video_bytes(job)
    required = (6. if uploading else 12. if size is None
                else min(12., max(6., math.ceil((4 + 1.5 + 3 * size / GIB) * 4) / 4)))
    return dict(kind=KIND, minRamGiB=required, minDiskGiB=20., maxCommitPercent=90,
                hostReserveGiB=4., taskReserveGiB=required - 4.,
                sourceVideoBytes=size, sourceSizeKnown=size is not None,
                uploading=uploading, modelLoaded=False)


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def findings(snapshot, profile, evaluate_fn=evaluate):
    """Keep RAM, commit percentage and absolute commit reserve independent.

    Windows commit counters measure a different constraint from free physical
    RAM. Both must admit the task. Linux keeps the underlying evaluator's own
    accounting rather than reinterpreting Linux commit as a Windows limit.
    ``profile=None`` delegates unchanged, including default heavy thresholds.
    """
    if profile is None:
        return evaluate_fn(snapshot)
    if (not isinstance(profile, dict) or profile.get('kind') != KIND
            or not _number(profile.get('minRamGiB')) or not 6 <= profile['minRamGiB'] <= 12
            or profile.get('minDiskGiB') != 20 or type(profile.get('minDiskGiB')) not in (int, float)
            or profile.get('maxCommitPercent') != 90 or type(profile.get('maxCommitPercent')) not in (int, float)
            or profile.get('hostReserveGiB') != 4 or type(profile.get('hostReserveGiB')) not in (int, float)
            or not _number(profile.get('taskReserveGiB')) or profile['taskReserveGiB'] < 2
            or profile['hostReserveGiB'] + profile['taskReserveGiB'] != profile['minRamGiB']
            or profile.get('modelLoaded') is not False):
        raise ValueError('route_reconstruction_resource_profile')
    result = list(evaluate_fn(snapshot, min_ram_gib=profile['minRamGiB'],
                              min_disk_gib=profile['minDiskGiB'],
                              max_commit_percent=profile['maxCommitPercent']))
    if snapshot.get('system') == 'Windows':
        used, limit = snapshot.get('committedBytes'), snapshot.get('commitLimitBytes')
        valid = (type(used) is int and type(limit) is int and 0 <= used <= limit and limit > 0)
        if not valid:
            if 'commit_measurement_unavailable' not in result:
                result.append('commit_measurement_unavailable')
        elif limit - used < profile['minRamGiB'] * GIB and 'commit_headroom_low' not in result:
            result.append('commit_headroom_low')
    return result
