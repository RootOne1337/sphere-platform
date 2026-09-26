"""A short Windows reader lock must not terminate a long operational test."""
import ctypes
import json
import os
import threading
from ctypes import wintypes
from pathlib import Path

import pytest

from scripts.pilot.android_soak import write_json


@pytest.mark.skipif(os.name != "nt", reason="Real Windows file sharing semantics")
def test_windows_reader_can_close_before_bounded_snapshot_retry(tmp_path):
    target = tmp_path / "status.json"
    write_json(target, {"generation": 1})
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0x80, None)
    assert handle != ctypes.c_void_p(-1).value
    timer = threading.Timer(0.075, kernel.CloseHandle, args=(handle,))
    timer.start()
    try:
        write_json(target, {"generation": 2})
        assert json.loads(target.read_text()) == {"generation": 2}
    finally:
        timer.join()


def test_persistent_windows_denial_remains_a_failure_and_preserves_previous_json(tmp_path, monkeypatch):
    target = tmp_path / "status.json"
    write_json(target, {"generation": 1})
    attempts = []

    def denied(*args):
        attempts.append(1)
        error = PermissionError(13, "denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        write_json(target, {"generation": 2})
    assert 1 < len(attempts) <= 6
    assert json.loads(target.read_text()) == {"generation": 1}


def test_other_write_errors_are_not_retried_or_hidden(tmp_path, monkeypatch):
    attempts = []

    def denied(*args):
        attempts.append(1)
        raise PermissionError(13, "permission denied without Windows sharing code")

    monkeypatch.setattr(Path, "replace", denied)
    with pytest.raises(PermissionError):
        write_json(tmp_path / "status.json", {})
    assert len(attempts) == 1
