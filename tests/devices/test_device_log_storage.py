from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from shutil import copytree

import pytest
from filelock import FileLock
from prometheus_client import REGISTRY

from backend.services import device_log_storage as storage
from backend.services.device_log_storage import (
    LegacyJournalOwnership,
    LogStorageQuotaExceeded,
    append_device_journal,
    delete_device_journal,
    sweep_device_journals,
)
from backend.services.device_log_upload import LogOwnershipLookupRequired


def _journal(root: Path, letter: str, name: str = "agent_2026-11-13.log") -> Path:
    return root / (letter * 32) / name


def _append(path: Path, data: bytes, *, daily_limit: int = 500, volume_limit: int = 500) -> None:
    append_device_journal(path, data, daily_limit=daily_limit, volume_limit=volume_limit, ttl_days=30)


def _retention_bytes(outcome: str) -> float:
    value = REGISTRY.get_sample_value("sphere_device_log_retention_bytes_total", {"outcome": outcome})
    assert value is not None
    return value


def test_device_daily_and_volume_caps_preserve_confirmed_history(tmp_path):
    daily_bytes = _retention_bytes("daily_quota")
    volume_bytes = _retention_bytes("volume_quota")
    first, second = _journal(tmp_path, "a"), _journal(tmp_path, "b")
    _append(first, b"A" * 280, daily_limit=300)
    with pytest.raises(LogStorageQuotaExceeded):
        _append(first, b"!" * 21, daily_limit=300)
    assert first.read_bytes() == b"A" * 280

    _append(second, b"B" * 220)
    with pytest.raises(LogStorageQuotaExceeded):
        _append(second, b"!")
    assert first.read_bytes() == b"A" * 280
    assert second.read_bytes() == b"B" * 220

    delete_device_journal(first.parent)
    assert not first.parent.exists()
    _append(second, b"C" * 280)
    assert second.stat().st_size == 500
    assert _retention_bytes("daily_quota") - daily_bytes == 21
    assert _retention_bytes("volume_quota") - volume_bytes == 1


def test_legacy_and_marked_journals_charge_only_their_owner_and_survive_restore(tmp_path):
    original = tmp_path / "original"
    legacy, foreign = _journal(original, "a"), _journal(original, "b")
    _append(legacy, b"legacy" * 10)
    _append(foreign, b"foreign")
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    target = _journal(original, "c")
    quota_bytes = _retention_bytes("org_quota")

    def append(path, data, owner=first, ownership=None):
        append_device_journal(path, data, daily_limit=200, volume_limit=200, ttl_days=30,
                              org_id=owner, org_limit=100, legacy=ownership)

    with pytest.raises(LogOwnershipLookupRequired) as lookup:
        append(target, b"A" * 40)
    assert lookup.value.directory_keys == frozenset({legacy.parent.name, foreign.parent.name})
    assert not target.exists()
    ownership = LegacyJournalOwnership(lookup.value.directory_keys, frozenset({legacy.parent.name}))
    append(target, b"A" * 40, ownership=ownership)

    restored = copytree(original, tmp_path / "restored")
    target = _journal(restored, "c")
    assert target.read_bytes() == b"A" * 40
    with pytest.raises(LogStorageQuotaExceeded):
        append(target, b"!", ownership=ownership)
    assert _retention_bytes("org_quota") - quota_bytes == 1
    assert target.read_bytes() == b"A" * 40

    with pytest.raises(OSError, match="different organization"):
        append(target, b"!", owner=second, ownership=ownership)
    other_target = _journal(restored, "d")
    other_ownership = LegacyJournalOwnership(ownership.checked, frozenset({foreign.parent.name}))
    append(other_target, b"B" * 90, owner=second, ownership=other_ownership)
    assert other_target.read_bytes() == b"B" * 90


def test_expiry_frees_organization_quota_and_removes_ownership_marker(tmp_path):
    org_id = str(uuid.uuid4())
    previous = _journal(tmp_path, "a", "agent_2000-01-01.log")
    target = _journal(tmp_path, "b")
    limits = dict(daily_limit=200, volume_limit=500, org_id=org_id, org_limit=100, ttl_days=30)
    append_device_journal(previous, b"x" * 100, **limits)
    with pytest.raises(LogStorageQuotaExceeded):
        append_device_journal(target, b"y" * 100, **limits)

    stale = time.time() - 31 * 86400
    for path in previous, tmp_path / storage.SWEEP_MARKER:
        os.utime(path, (stale, stale))
    sweep_device_journals(tmp_path)
    assert not previous.parent.exists()
    append_device_journal(target, b"y" * 100, **limits)
    assert target.read_bytes() == b"y" * 100


def test_concurrent_processes_share_organization_quota(tmp_path):
    script = """
import sys
from pathlib import Path
from backend.services.device_log_storage import append_device_journal, LogStorageQuotaExceeded
try:
    append_device_journal(
        Path(sys.argv[1]), b'x' * 300, daily_limit=500, volume_limit=1200, ttl_days=30,
        org_id=sys.argv[2], org_limit=500,
    )
except LogStorageQuotaExceeded:
    sys.exit(3)
"""
    org_id = str(uuid.uuid4())
    commands = ([sys.executable, "-c", script, str(_journal(tmp_path, key)), org_id] for key in "ab")
    children = [subprocess.Popen(command) for command in commands]
    try:
        assert sorted(child.wait(timeout=15) for child in children) == [0, 3]
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    assert sum(path.stat().st_size for path in tmp_path.glob("*/agent_*.log")) == 300


@pytest.mark.skipif(sys.platform != "win32", reason="Windows directory junction")
def test_device_journal_junction_never_reads_writes_or_expires_its_target(tmp_path):
    import _winapi

    from backend.services.device_log_reader import LogReadUnavailable, read_log_dates

    root, outside = tmp_path / "managed", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    outside_journal = outside / "agent_2000-01-01.log"
    outside_journal.write_bytes(b"outside")
    stale = time.time() - 31 * 86400
    os.utime(outside_journal, (stale, stale))
    directory = _journal(root, "a").parent
    _winapi.CreateJunction(str(outside), str(directory))
    try:
        with pytest.raises(OSError, match="Invalid managed"):
            sweep_device_journals(root)
        with pytest.raises(OSError, match="Invalid managed"):
            _append(_journal(root, "a"), b"inside")
        with pytest.raises(OSError, match="Invalid managed"):
            delete_device_journal(directory)
        with pytest.raises(LogReadUnavailable):
            read_log_dates(directory)
        assert outside_journal.read_bytes() == b"outside"
        assert not (outside / _journal(root, "a").name).exists()
    finally:
        directory.rmdir()


def test_upload_sweeps_expired_managed_files_from_inactive_devices(tmp_path):
    old = _journal(tmp_path, "a", "agent_2000-01-01.log")
    old.parent.mkdir()
    old.write_bytes(b"old" * 200)
    other_file = old.parent / "manual-notes.txt"
    other_file.write_bytes(b"keep")
    timestamp = time.time() - 31 * 86400
    os.utime(old, (timestamp, timestamp))
    os.utime(other_file, (timestamp, timestamp))

    active = _journal(tmp_path, "b")
    _append(active, b"new")
    assert not old.exists()
    assert other_file.read_bytes() == b"keep"
    assert active.read_bytes() == b"new"


def test_idle_sweep_preserves_fresh_journals_and_throttles_all_workers(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_MAX_EXPIRED_PER_SWEEP", 1)
    expired_bytes = _retention_bytes("expired")
    expired = [_journal(tmp_path, "a", f"agent_2000-01-0{day}.log") for day in (1, 2)]
    fresh = _journal(tmp_path, "b")
    fresh.parent.mkdir()
    fresh.write_bytes(b"preserve")
    expired[0].parent.mkdir()
    stale = time.time() - 31 * 86400
    for path in expired:
        path.write_bytes(b"old")
        os.utime(path, (stale, stale))

    sweep_device_journals(tmp_path)
    assert sum(path.exists() for path in expired) == 1
    assert _retention_bytes("expired") - expired_bytes == 3
    sweep_device_journals(tmp_path)
    assert sum(path.exists() for path in expired) == 1
    assert _retention_bytes("expired") - expired_bytes == 3

    marker = tmp_path / storage.SWEEP_MARKER
    os.utime(marker, (stale, stale))
    sweep_device_journals(tmp_path)
    assert not any(path.exists() for path in expired)
    os.utime(marker, (stale, stale))
    sweep_device_journals(tmp_path)
    assert not expired[0].parent.exists()
    assert fresh.read_bytes() == b"preserve"
    assert _retention_bytes("expired") - expired_bytes == 6


def test_cross_process_writer_cannot_bypass_shared_storage_lock(tmp_path):
    script = """
import sys
from pathlib import Path
from backend.services.device_log_storage import append_device_journal, LogStorageQuotaExceeded
from backend.services.device_log_upload import LogUploadBusy
try:
    append_device_journal(Path(sys.argv[1]), b'x' * 300, daily_limit=500, volume_limit=500, ttl_days=30)
except LogUploadBusy:
    sys.exit(2)
except LogStorageQuotaExceeded:
    sys.exit(3)
"""
    arguments = [sys.executable, "-c", script, str(_journal(tmp_path, "b"))]
    with FileLock(tmp_path / ".device-logs.lock"):
        assert subprocess.run(arguments, check=False, timeout=10).returncode == 2

    _append(_journal(tmp_path, "a"), b"a" * 300)
    assert subprocess.run(arguments, check=False, timeout=10).returncode == 3
    assert not _journal(tmp_path, "b").exists()


def test_failed_unlink_does_not_count_expired_bytes(tmp_path, monkeypatch):
    old = _journal(tmp_path, "a", "agent_2000-01-01.log")
    old.parent.mkdir()
    old.write_bytes(b"old")
    timestamp = time.time() - 31 * 86400
    os.utime(old, (timestamp, timestamp))
    expired_bytes = _retention_bytes("expired")
    unlink = os.unlink

    def fail_unlink(path, *args, **kwargs):
        if Path(path) == old:
            raise PermissionError("fixture")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(storage.os, "unlink", fail_unlink)
    with pytest.raises(PermissionError, match="fixture"):
        sweep_device_journals(tmp_path)
    assert old.exists()
    assert _retention_bytes("expired") == expired_bytes


def test_retention_and_catalog_work_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "_MAX_EXPIRED_PER_SWEEP", 1)
    old = [_journal(tmp_path, letter, "agent_2000-01-01.log") for letter in "ab"]
    for path in old:
        path.parent.mkdir()
        path.write_bytes(b"old")
        timestamp = time.time() - 31 * 86400
        os.utime(path, (timestamp, timestamp))

    active = _journal(tmp_path, "c")
    _append(active, b"first")
    assert sum(path.exists() for path in old) == 1
    _append(active, b"second")
    assert sum(path.exists() for path in old) == 1

    monkeypatch.setattr(storage, "_MAX_CATALOG_ENTRIES", 3)
    with pytest.raises(OSError, match="scan budget"):
        _append(active, b"third")
    assert active.read_bytes() == b"firstsecond"


def test_short_write_rolls_back_without_losing_confirmed_history(tmp_path, monkeypatch):
    target = _journal(tmp_path, "a")
    _append(target, b"confirmed")
    actual_open = Path.open

    class ShortWriter:
        def __enter__(self):
            self.stream = actual_open(target, "ab", buffering=0)
            return self

        def __exit__(self, *_):
            self.stream.close()

        def write(self, data):
            return self.stream.write(data[:4])

        def truncate(self, size):
            self.stream.truncate(size)

    def open_file(path, mode, **kwargs):
        return ShortWriter() if path == target and mode == "ab" else actual_open(path, mode, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", open_file)
        with pytest.raises(OSError, match="Incomplete"):
            _append(target, b"interrupted")
    assert target.read_bytes() == b"confirmed"
