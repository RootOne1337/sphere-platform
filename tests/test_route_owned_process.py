"""Harmless owned children only; no reconstruction, game input or real jobs."""
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from types import SimpleNamespace

import pytest

from scripts.pilot import route_owned_process as owned


def test_assignment_precedes_resume_without_a_new_memory_limit(monkeypatch):
    events = []
    process = SimpleNamespace(pid=123, poll=lambda: None)
    class Job:
        def __init__(self): events.append('job')
        def assign(self, child):
            assert child is process
            events.append('assign')
        def close(self): events.append('close')
    def popen(command, **kwargs):
        assert kwargs['creationflags'] == 0x08004004
        events.append('suspended_spawn')
        return process
    monkeypatch.setattr(owned, '_WindowsJob', Job)
    monkeypatch.setattr(owned.subprocess, 'Popen', popen)
    monkeypatch.setattr(owned, '_resume_primary', lambda child: events.append('resume') or 456)
    monkeypatch.setattr(owned, 'os', SimpleNamespace(name='nt'))
    worker = owned.spawn_owned(['known-worker'], creationflags=0x08004000)
    assert events == ['job', 'suspended_spawn', 'assign', 'resume']
    assert worker.ownership == dict(policy='suspended_job_kill_on_close', pid=123,
                                   primaryThreadId=456, addsMemoryLimit=False, ownsDescendants=True)
    worker.close()
    worker.close()
    assert events.count('close') == 1


@pytest.mark.parametrize('stage', ['popen', 'assign', 'resume'])
def test_startup_failure_closes_job_and_reaps_only_owned_child(monkeypatch, stage):
    events = []
    process = SimpleNamespace(pid=123, poll=lambda: None,
                              kill=lambda: events.append('kill'), wait=lambda timeout: events.append('reap'))
    class Job:
        def assign(self, child):
            if stage == 'assign':
                raise OSError('assignment refused')
        def close(self): events.append('close')
    def popen(*args, **kwargs):
        if stage == 'popen':
            raise OSError('launch refused')
        return process
    def resume(child):
        if stage == 'resume':
            raise OSError('thread identity refused')
    monkeypatch.setattr(owned, '_WindowsJob', Job)
    monkeypatch.setattr(owned.subprocess, 'Popen', popen)
    monkeypatch.setattr(owned, '_resume_primary', resume)
    monkeypatch.setattr(owned, 'os', SimpleNamespace(name='nt'))
    with pytest.raises(OSError):
        owned.spawn_owned(['known-worker'])
    assert events == (['close'] if stage == 'popen' else ['close', 'kill', 'reap'])


def test_non_windows_fallback_does_not_claim_parent_death_or_tree_ownership(monkeypatch):
    events = []
    process = SimpleNamespace(pid=123, poll=lambda: None,
                              kill=lambda: events.append('kill'), wait=lambda timeout: events.append('reap'))
    monkeypatch.setattr(owned, 'os', SimpleNamespace(name='posix'))
    monkeypatch.setattr(owned.subprocess, 'Popen', lambda *a, **k: process)
    worker = owned.spawn_owned(['known-worker'])
    assert worker.ownership['ownsDescendants'] is False
    assert worker.ownership['policy'] == 'direct_child_cooperative_cancel'
    worker.stop(timeout=2)
    assert events == ['kill', 'reap']


@pytest.mark.skipif(os.name != 'nt', reason='Windows kernel process ownership')
def test_real_windows_owned_child_runs_after_assignment_and_closes(tmp_path):
    marker = tmp_path/'started.json'
    command = [sys.executable, '-B', '-c',
               "import os,json,sys;from pathlib import Path;Path(sys.argv[1]).write_text(json.dumps({'pid':os.getpid()}))",
               str(marker)]
    worker = owned.spawn_owned(command, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert worker.wait(timeout=5) == 0
        assert marker.is_file()
        assert worker.ownership['primaryThreadId'] > 0
        assert worker.ownership['addsMemoryLimit'] is False
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                     wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetHandleInformation.restype = wintypes.BOOL
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('active_process_limit', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling_class', wintypes.DWORD)]
        data = BasicLimits()
        returned, handle_flags = wintypes.DWORD(), wintypes.DWORD()
        assert kernel.QueryInformationJobObject(worker.job.handle, 2, ctypes.byref(data), ctypes.sizeof(data),
                                                 ctypes.byref(returned)), ctypes.get_last_error()
        limit_flags = data.flags
        assert limit_flags == owned.KILL_ON_JOB_CLOSE  # No memory/affinity/priority limits.
        assert kernel.GetHandleInformation(worker.job.handle, ctypes.byref(handle_flags))
        assert not handle_flags.value & 1  # HANDLE_FLAG_INHERIT
        print(json.dumps(dict(test='owned_child', launchedPid=worker.pid,
                              pythonPid=json.loads(marker.read_text())['pid'], ownership=worker.ownership,
                              kernelLimitFlags=limit_flags, inheritable=False)))
    finally:
        worker.stop(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows kernel process ownership')
def test_executor_death_kills_venv_child_and_grandchild(tmp_path):
    """Parent termination closes the sole job handle, without a tree/PID kill."""
    evidence = tmp_path/'pids.json'
    child_code = (
        "import subprocess,sys,time,json,os;from pathlib import Path;"
        "p=subprocess.Popen([sys._base_executable,'-B','-c','import time;time.sleep(20)']);"
        "Path(sys.argv[1]).write_text(json.dumps({'child':os.getpid(),'grandchild':p.pid}));time.sleep(20)"
    )
    driver_code = (
        "import sys,time;from scripts.pilot.route_owned_process import spawn_owned;"
        "p=spawn_owned([sys.argv[3],'-B','-c',sys.argv[2],sys.argv[1]],creationflags=0x08000000);"
        "time.sleep(20)"
    )
    driver = subprocess.Popen([sys._base_executable, '-B', '-c', driver_code, str(evidence), child_code, sys.executable],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              creationflags=subprocess.CREATE_NO_WINDOW)
    handles = []
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    try:
        deadline = time.monotonic()+5
        while not evidence.exists() and time.monotonic()<deadline and driver.poll() is None:
            time.sleep(.01)
        assert evidence.exists(), 'driver failed to start owned child'
        pids = json.loads(evidence.read_text())
        for pid in pids.values():
            handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE, held exact identity
            assert handle
            handles.append(handle)
        driver.terminate()  # Only the explicitly created executor, not its tree.
        driver.wait(timeout=5)
        assert all(kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles)
        print(json.dumps(dict(test='executor_crash', driver=driver.pid, **pids, childrenExited=True)))
    finally:
        if driver.poll() is None:
            driver.kill()
            driver.wait(timeout=5)
        for handle in handles:
            kernel.CloseHandle(handle)
        driver.stderr.close()
