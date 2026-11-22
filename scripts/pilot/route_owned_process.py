"""Own route workers before their first instruction, without changing budgets.

Windows creates a suspended process, assigns a non-inheritable kill-on-close
job, then resumes its uniquely verified primary thread. Thus even a venv
launcher cannot spawn a descendant before ownership is established. No memory,
priority, affinity or breakaway limits are added. On other platforms only the
direct Popen child is owned; cooperative cancellation remains necessary.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

CREATE_SUSPENDED = 0x00000004
KILL_ON_JOB_CLOSE = 0x00002000


class _WindowsJob:
    def __init__(self):
        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t),
                        ('max_working_set', ctypes.c_size_t), ('active_process_limit', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling_class', wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('reads', 'writes', 'others', 'read_bytes', 'write_bytes', 'other_bytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self.handle = None
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        self.kernel.SetHandleInformation.restype = wintypes.BOOL
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.SetInformationJobObject.restype = wintypes.BOOL
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            # No child may inherit the sole lifetime handle and keep the job
            # alive after the API dies. Only KILL_ON_JOB_CLOSE is configured.
            if not self.kernel.SetHandleInformation(self.handle, 1, 0):
                raise ctypes.WinError(ctypes.get_last_error())
            limits = ExtendedLimits()
            limits.basic.flags = KILL_ON_JOB_CLOSE
            if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def assign(self, process):
        # Popen retains a handle to this exact process, not a PID reopened later.
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _resume_primary(process):
    """Resume only the unique thread of our still-suspended, held process."""
    class ThreadEntry(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('usage', wintypes.DWORD),
                    ('thread_id', wintypes.DWORD), ('owner_id', wintypes.DWORD),
                    ('base_priority', wintypes.LONG), ('delta_priority', wintypes.LONG),
                    ('flags', wintypes.DWORD)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for name in ('Thread32First', 'Thread32Next'):
        method = getattr(kernel, name)
        method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
        method.restype = wintypes.BOOL
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.GetProcessIdOfThread.argtypes = [wintypes.HANDLE]
    kernel.GetProcessIdOfThread.restype = wintypes.DWORD
    kernel.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel.ResumeThread.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    threads = []
    try:
        entry = ThreadEntry()
        entry.size = ctypes.sizeof(entry)
        success = kernel.Thread32First(snapshot, ctypes.byref(entry))
        count = 0
        while success:
            count += 1
            if count > 65536:
                raise OSError('route_thread_snapshot_quota')
            if entry.owner_id == process.pid:
                threads.append(entry.thread_id)
            entry.size = ctypes.sizeof(entry)
            success = kernel.Thread32Next(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.CloseHandle(snapshot)
    if len(threads) != 1 or process.poll() is not None:
        raise OSError('route_suspended_primary_not_unique')
    handle = kernel.OpenThread(0x0802, False, threads[0])  # QUERY_LIMITED + SUSPEND_RESUME
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if kernel.GetProcessIdOfThread(handle) != process.pid:
            raise OSError('route_suspended_thread_owner_changed')
        if kernel.ResumeThread(handle) != 1:
            raise OSError('route_primary_suspend_count_changed')
    finally:
        kernel.CloseHandle(handle)
    return threads[0]


class OwnedProcess:
    def __init__(self, process, job=None, primary_thread=None):
        self.process, self.job = process, job
        self.ownership = dict(policy='suspended_job_kill_on_close' if job else 'direct_child_cooperative_cancel',
                              pid=process.pid, primaryThreadId=primary_thread,
                              addsMemoryLimit=False, ownsDescendants=job is not None)

    def __getattr__(self, name):
        return getattr(self.process, name)

    def close(self):
        if self.job is not None:
            self.job.close()
            self.job = None

    def stop(self, timeout=10):
        if self.job is not None:
            self.close()  # Atomically terminates only the assigned process tree.
        elif self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=timeout)


def spawn_owned(command, **kwargs):
    """Return only after ownership is established; startup failure reaps child."""
    job = _WindowsJob() if os.name == 'nt' else None
    process = None
    try:
        if job is not None:
            kwargs['creationflags'] = kwargs.get('creationflags', 0) | CREATE_SUSPENDED
        process = subprocess.Popen(command, **kwargs)
        primary_thread = None
        if job is not None:
            job.assign(process)
            primary_thread = _resume_primary(process)
        return OwnedProcess(process, job, primary_thread)
    except BaseException:
        try:
            if job is not None:
                job.close()
        finally:
            if process is not None:
                try:
                    if process.poll() is None:
                        process.kill()
                finally:
                    process.wait(timeout=10)
        raise
