"""Finite C: NTFS journal observation: changed paths and exact live file sizes.

Read-only, elevated, metadata only. No journal creation/deletion or cleanup.
USN has no writer PID. Pair these growth observations with kernel ETW captures.
First observations are baselines, not proof those whole files were newly created.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import struct
import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.disk_growth import file_state, reparse
from scripts.pilot.host_storage_watch import privilege_mode

MIB = 1024 ** 2
DATA_REASONS = 0x00000007 | 0x00000070 | 0x00000300 | 0x00003000


def records(data: bytes) -> tuple[int, list[dict]]:
    """Strict USN_RECORD_V2 parser; unsupported versions are an explicit gap."""
    if len(data) < 8:
        raise ValueError('Missing journal cursor')
    cursor = struct.unpack_from('<q', data)[0]
    offset = 8
    rows = []
    while offset < len(data):
        if len(data) - offset < 60:
            raise ValueError('Truncated journal record')
        length, major, _minor = struct.unpack_from('<IHH', data, offset)
        if major != 2 or length < 60 or length % 8 or offset + length > len(data):
            raise ValueError('Unsupported or invalid journal record')
        file_id, parent_id, usn, _stamp, reason = struct.unpack_from('<QQqqI', data, offset + 8)
        name_length, name_offset = struct.unpack_from('<HH', data, offset + 56)
        if name_offset < 60 or name_length % 2 or name_offset + name_length > length:
            raise ValueError('Invalid journal filename bounds')
        name = data[offset + name_offset:offset + name_offset + name_length].decode('utf-16-le')
        rows.append({'fileId': file_id, 'parentId': parent_id, 'usn': usn,
                     'reason': reason, 'name': name})
        offset += length
    return cursor, rows


class Journal:
    def __init__(self):
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                                        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        self.api.CreateFileW.restype = ctypes.c_void_p
        self.api.DeviceIoControl.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                            ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
                                            ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
        self.api.DeviceIoControl.restype = ctypes.c_int
        self.api.CloseHandle.argtypes = [ctypes.c_void_p]
        self.api.OpenFileById.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
                                          ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
        self.api.OpenFileById.restype = ctypes.c_void_p
        self.api.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                                     ctypes.c_uint32, ctypes.c_uint32]
        self.api.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
        self.handle = self.api.CreateFileW('\\\\.\\C:', 0x80000000, 7, None, 3, 0, None)
        if self.handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        self.api.CloseHandle(self.handle)

    def control(self, code: int, payload: bytes, capacity: int) -> bytes:
        source = ctypes.create_string_buffer(payload) if payload else None
        result = ctypes.create_string_buffer(capacity)
        returned = ctypes.c_uint32()
        if not self.api.DeviceIoControl(self.handle, code, source, len(payload), result,
                                       capacity, ctypes.byref(returned), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.raw[:returned.value]

    def query(self) -> dict:
        data = self.control(0x000900F4, b'', 128)
        if len(data) < 56:
            raise ValueError('Incomplete journal identity')
        identity, first, next_usn, lowest, _max, _size, _delta = struct.unpack_from('<QqqqqQQ', data)
        return {'id': identity, 'first': first, 'next': next_usn, 'lowest': lowest}

    def read(self, identity: int, cursor: int, end: int) -> tuple[int, list[dict], int]:
        result: dict[int, dict] = {}
        used = 0
        timer = time.monotonic()
        while cursor < end:
            if used >= 8 * MIB or time.monotonic() - timer > 10:
                raise ValueError('Journal backlog exceeds bounded cycle; coverage gap')
            payload = struct.pack('<qIIQQQ', cursor, DATA_REASONS, 0, 0, 0, identity)
            data = self.control(0x000900BB, payload, 64 * 1024)
            used += len(data)
            next_usn, changed = records(data)
            if next_usn <= cursor:
                raise ValueError('Journal read did not advance')
            for row in changed:
                # Keep records appended after the query too: read may advance
                # past its earlier endpoint. Filtering them would lose writes.
                result[row['fileId']] = row
            if len(result) > 4096:
                raise ValueError('Changed-ID budget exceeded; coverage gap')
            cursor = next_usn
        return cursor, list(result.values()), used

    def resolve(self, file_id: int) -> dict:
        # FILE_ID_DESCRIPTOR: DWORD size, enum type=FileIdType, 16-byte union.
        descriptor = ctypes.create_string_buffer(struct.pack('<IIQ8x', 24, 0, file_id))
        handle = self.api.OpenFileById(self.handle, descriptor, 0, 7, None, 0x02200000)
        if handle == ctypes.c_void_p(-1).value:
            return {'state': 'unavailable', 'errorType': f'win32_{ctypes.get_last_error()}'}
        try:
            text = ctypes.create_unicode_buffer(32768)
            size = self.api.GetFinalPathNameByHandleW(handle, text, len(text), 0)
            if not size or size >= len(text) or not text.value.startswith('\\\\?\\C:\\'):
                return {'state': 'unavailable', 'errorType': 'unresolved_or_outside_C'}
            path = Path(text.value[4:])
            measured = file_state(path)
            # Validate the measured file still has the journal identity after
            # path resolution; an atomic replacement is not the same file.
            if measured.get('state') == 'measured' and measured['identity'][1] != file_id:
                return {'state': 'unavailable', 'errorType': 'identity_changed'}
            return {'path': str(path), **measured}
        finally:
            self.api.CloseHandle(handle)


def growth(previous: dict | None, current: dict) -> dict:
    if previous is None:
        return {'state': 'baseline', 'allocatedDeltaBytes': None, 'logicalDeltaBytes': None}
    if (previous.get('state') != 'measured' or current.get('state') != 'measured'
            or previous.get('identity') != current.get('identity')):
        return {'state': 'incomparable', 'allocatedDeltaBytes': None, 'logicalDeltaBytes': None}
    a, b = previous.get('allocatedBytes'), current.get('allocatedBytes')
    return {'state': 'comparable', 'allocatedDeltaBytes': b - a
            if type(a) is int and type(b) is int else None,
            'logicalDeltaBytes': current['logicalBytes'] - previous['logicalBytes']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=241)
    parser.add_argument('--interval', type=int, default=120)
    args = parser.parse_args()
    base = Path(__file__).resolve().parents[2] / '.local-pilot'
    try:
        privilege_mode(allow_unprivileged=False)
        if (not 2 <= args.samples <= 721 or not 60 <= args.interval <= 600
                or (args.samples - 1) * args.interval > 86400):
            raise ValueError('Finite observation up to 24 hours required')
        output = args.output_dir.absolute()
        if output.parent != base or reparse(base.stat(follow_symlinks=False)):
            raise ValueError('Fresh direct workspace private report required')
        journal = Journal()
        initial = journal.query()
        output.mkdir(exist_ok=False)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    status = {'state': 'running', 'pid': os.getpid(), 'administrator': True,
              'startedUtc': datetime.now(timezone.utc).isoformat(), 'samplesLimit': args.samples,
              'intervalSeconds': args.interval, 'samplesWritten': 0, 'reportBytes': 0,
              'reportLimitBytes': 16 * MIB, 'journalCreatedOrChanged': False,
              'fileContentsRead': False, 'cleanupPerformed': False,
              'writerPidProvidedByUsn': False, 'resolvedFilesLimitPerCycle': 256,
              'measurementCacheLimit': 4096, 'journalReadLimitBytesPerCycle': 8 * MIB}
    cursor = initial['next']
    previous: dict[int, dict] = {}
    timer = time.monotonic()
    try:
        with (output / 'samples.jsonl').open('xb', buffering=0) as stream:
            for index in range(args.samples):
                if index:
                    time.sleep(max(0, timer + index * args.interval - time.monotonic()))
                current = journal.query()
                if current['id'] != initial['id'] or cursor < current['first']:
                    raise ValueError('Journal changed or wrapped; coverage gap')
                cursor, changed, read_bytes = journal.read(initial['id'], cursor, current['next'])
                files = []
                selected = sorted(changed, key=lambda row: (bool(row['reason'] & 2), row['usn']), reverse=True)[:256]
                for row in selected:
                    measured = journal.resolve(row['fileId'])
                    if measured.get('path') and output in Path(measured['path']).parents:
                        continue
                    delta = growth(previous.get(row['fileId']), measured)
                    files.append({**row, 'measurement': measured, 'growth': delta})
                    previous.pop(row['fileId'], None)
                    previous[row['fileId']] = measured
                while len(previous) > 4096:
                    previous.pop(next(iter(previous)))
                record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'index': index,
                          'journal': current, 'readBytes': read_bytes, 'files': files,
                          'changedFileCount': len(changed),
                          'resolutionState': 'complete' if len(changed) <= 256 else 'partial_budget',
                          'unresolvedByBudget': max(0, len(changed) - 256),
                          'writerAttribution': 'USN_HAS_NO_PID'}
                encoded = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
                if len(encoded) > 256 * 1024 or status['reportBytes'] + len(encoded) > 16 * MIB - 32768:
                    raise ValueError('Report budget exceeded')
                stream.write(encoded)
                status.update(samplesWritten=index + 1, reportBytes=status['reportBytes'] + len(encoded),
                              lastSampleUtc=record['observedUtc'])
                write_json(output / 'status.json', status)
                if shutil.disk_usage('C:\\').free < 512 * MIB:
                    status['state'] = 'stopped_low_disk'
                    break
            else:
                status['state'] = 'complete'
    except (OSError, ValueError) as error:
        status.update(state='stopped_error', errorType=type(error).__name__, error=str(error)[:256])
    except KeyboardInterrupt:
        status['state'] = 'interrupted'
    finally:
        journal.close()
        status['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'status.json', status)
    print(json.dumps(status))
    return 0 if status['state'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
