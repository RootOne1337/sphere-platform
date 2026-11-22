"""Serialize mutations and bound storage for managed Android device journals."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock, Timeout

from backend.metrics import (
    device_log_retention_bytes_total,
    device_log_retention_events_total,
    device_log_storage_lock_busy_total,
    device_log_upload_bytes_total,
)
from backend.services.device_log_upload import LogOwnershipLookupRequired, LogUploadBusy

_DEVICE_DIR = re.compile(r"[a-f0-9]{32}\Z")
_JOURNAL = re.compile(r"agent_\d{4}-\d{2}-\d{2}\.log\Z")
_ORG_OWNER = re.compile(r"\.org-([a-f0-9]{32})\Z")
DEVICE_LOG_ROOT = Path(os.environ.get("SPHERE_LOGS_DIR", "/tmp/sphere_device_logs"))  # nosec B108
JOURNAL_RETENTION_DAYS = 30
MAINTENANCE_INTERVAL_SECONDS = 60
SWEEP_MARKER = ".device-logs-sweep"
_MAX_EXPIRED_PER_SWEEP = 128
_MAX_CATALOG_ENTRIES = 50_000
_LOCK_WAIT_SECONDS = 1.0
_LOCK_POLL_SECONDS = 0.01


class LogStorageQuotaExceeded(Exception):
    pass


@dataclass(frozen=True)
class LegacyJournalOwnership:
    checked: frozenset[str]
    owned: frozenset[str]


@dataclass
class _JournalUsage:
    volume_bytes: int = 0
    organization_bytes: int = 0
    target_owner: str | None = None
    unchecked: set[str] = field(default_factory=set)


def device_journal_key(device_id: str) -> str:
    """Keep the existing on-disk path for a canonical device UUID."""
    return hashlib.sha256(device_id.encode()).hexdigest()[:32]


def _organization_key(org_id: str) -> str:
    return hashlib.sha256(f"sphere:device-journals:{org_id}".encode()).hexdigest()[:32]


@contextmanager
def _locked(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.is_junction():
        raise OSError("Device log root must be a directory")
    lock_path = root / ".device-logs.lock"
    if lock_path.is_symlink():
        raise OSError("Device log lock must be local to the journal root")
    try:
        with FileLock(lock_path).acquire(timeout=_LOCK_WAIT_SECONDS, poll_interval=_LOCK_POLL_SECONDS):
            yield
    except Timeout as exc:
        device_log_storage_lock_busy_total.inc()
        raise LogUploadBusy() from exc


def _sweep_due(marker: Path, now: float) -> bool:
    if marker.is_symlink():
        raise OSError("Invalid device log retention marker")
    try:
        return now - marker.stat().st_mtime >= MAINTENANCE_INTERVAL_SECONDS
    except FileNotFoundError:
        return True


def _scan_journals(
    root: Path, *, expiry_cutoff: float | None, org_key: str | None = None,
    target_key: str | None = None, legacy: LegacyJournalOwnership | None = None,
) -> _JournalUsage:
    removed = scanned = 0
    usage = _JournalUsage()
    with os.scandir(root) as devices:
        for device in devices:
            scanned += 1
            if scanned > _MAX_CATALOG_ENTRIES:
                raise OSError("Device log catalog exceeds the scan budget")
            if not _DEVICE_DIR.fullmatch(device.name):
                continue
            if not device.is_dir(follow_symlinks=False) or os.path.isjunction(device.path):
                raise OSError("Invalid managed device log directory")
            has_retained_files = False
            owner: str | None = None
            owner_path: str | None = None
            device_bytes = 0
            with os.scandir(device.path) as files:
                for entry in files:
                    scanned += 1
                    if scanned > _MAX_CATALOG_ENTRIES:
                        raise OSError("Device log catalog exceeds the scan budget")
                    if not entry.is_file(follow_symlinks=False):
                        raise OSError("Invalid managed device log file")
                    metadata = entry.stat(follow_symlinks=False)
                    if (match := _ORG_OWNER.fullmatch(entry.name)) is not None:
                        if owner is not None or metadata.st_size != 0:
                            raise OSError("Invalid managed device log ownership")
                        owner, owner_path = match[1], entry.path
                        continue
                    if (expiry_cutoff is not None and removed < _MAX_EXPIRED_PER_SWEEP
                            and metadata.st_mtime < expiry_cutoff
                            and _JOURNAL.fullmatch(entry.name)):
                        os.unlink(entry.path)
                        removed += 1
                        device_log_retention_events_total.labels(outcome="expired").inc()
                        device_log_retention_bytes_total.labels(outcome="expired").inc(metadata.st_size)
                    else:
                        has_retained_files = True
                        device_bytes += metadata.st_size
            if expiry_cutoff is not None and removed < _MAX_EXPIRED_PER_SWEEP and not has_retained_files:
                if owner_path is not None:
                    os.unlink(owner_path)
                os.rmdir(device.path)
                removed += 1
                owner = None
            usage.volume_bytes += device_bytes
            if device.name == target_key:
                usage.target_owner = owner
            if org_key is None or device_bytes == 0:
                continue
            if owner == org_key or (owner is None and device.name == target_key):
                usage.organization_bytes += device_bytes
            elif owner is None:
                if legacy is None or device.name not in legacy.checked:
                    usage.unchecked.add(device.name)
                elif device.name in legacy.owned:
                    usage.organization_bytes += device_bytes
    return usage


def _scan_and_sweep(
    root: Path, ttl_days: int, *, only_if_due: bool = False, org_key: str | None = None,
    target_key: str | None = None, legacy: LegacyJournalOwnership | None = None,
) -> _JournalUsage:
    marker = root / SWEEP_MARKER
    now = time.time()
    sweep = _sweep_due(marker, now)
    if only_if_due and not sweep:
        return _JournalUsage()  # Maintenance has no use for occupied bytes.
    usage = _scan_journals(
        root, expiry_cutoff=now - ttl_days * 86400 if sweep else None,
        org_key=org_key, target_key=target_key, legacy=legacy,
    )
    if sweep:
        marker.touch()
    return usage


def sweep_device_journals(root: Path, *, ttl_days: int = JOURNAL_RETENTION_DAYS) -> None:
    """Apply the same bounded expiry without waiting for another device upload."""
    if not root.exists() or not _sweep_due(root / SWEEP_MARKER, time.time()):
        return
    with _locked(root):
        _scan_and_sweep(root, ttl_days, only_if_due=True)


def _reject_quota(outcome: str, entry_size: int) -> None:
    device_log_retention_events_total.labels(outcome=outcome).inc()
    device_log_retention_bytes_total.labels(outcome=outcome).inc(entry_size)
    raise LogStorageQuotaExceeded()


def append_device_journal(
    path: Path, entry: bytes, *, daily_limit: int, volume_limit: int, ttl_days: int,
    org_id: str | None = None, org_limit: int | None = None, legacy: LegacyJournalOwnership | None = None,
) -> None:
    root = path.parent.parent
    entry_size = len(entry)
    if (org_id is None) != (org_limit is None):
        raise ValueError("Journal organization and quota must be supplied together")
    org_key = _organization_key(org_id) if org_id is not None else None
    with _locked(root):
        usage = _scan_and_sweep(root, ttl_days, org_key=org_key, target_key=path.parent.name, legacy=legacy)
        if org_key is not None and usage.target_owner not in (None, org_key):
            raise OSError("Managed device log belongs to a different organization")
        current = path.stat().st_size if path.exists() else 0
        if current + entry_size > daily_limit:
            _reject_quota("daily_quota", entry_size)
        if usage.volume_bytes + entry_size > volume_limit:
            _reject_quota("volume_quota", entry_size)
        if org_limit is not None:
            if usage.unchecked:
                raise LogOwnershipLookupRequired(frozenset(usage.unchecked))
            if usage.organization_bytes + entry_size > org_limit:
                _reject_quota("org_quota", entry_size)
        path.parent.mkdir(exist_ok=True)
        if org_key is not None and usage.target_owner is None:
            # Atomic marker creation under the shared lock. A crash between
            # marker creation and append leaves an empty directory to sweep.
            (path.parent / f".org-{org_key}").touch(exist_ok=False)
        with path.open("ab", buffering=0) as stream:
            try:
                if stream.write(entry) != entry_size:
                    raise OSError("Incomplete device journal append")
            except OSError:
                # A short write must not leave a partial, unacknowledged entry
                # mixed with retained history. The same lock fences rollback.
                stream.truncate(current)
                raise
        device_log_upload_bytes_total.inc(entry_size)


def delete_device_journal(directory: Path) -> None:
    with _locked(directory.parent):
        if directory.is_symlink() or directory.is_junction():
            raise OSError("Invalid managed device log directory")
        if directory.exists():
            shutil.rmtree(directory)
