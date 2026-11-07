"""Filesystem, memory/admission and HTTP boundaries for retained device logs."""
from __future__ import annotations

import asyncio
import importlib
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from backend.services import device_log_reader as reader


def write_log(directory: Path, name: str, content: bytes) -> Path:
    directory.mkdir(exist_ok=True)
    path = directory / f"agent_{name}.log"
    path.write_bytes(content)
    return path


def read(directory, lines=1000, date=None, search=None):
    return reader.read_log_tail(directory, lines=lines, date=date, search=search)


@pytest.mark.parametrize('payload', [b'', b'\n', b'a', b'a\n', b'a\nb', b'a\nb\n', b'a\n\nb\n', b'a\r\nb\r\n'])
def test_complete_small_tail_preserves_line_content_and_order(tmp_path, payload):
    write_log(tmp_path, '2026-10-06', payload)
    result = read(tmp_path)
    assert result['lines'] == payload.decode().splitlines()
    assert not result['read']['truncated']
    assert result['read']['bytes_scanned'] == len(payload)


def test_reverse_chunk_boundaries_utf8_and_tail_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'CHUNK_BYTES', 7)
    content = 'первая\nвторая\nтретья\n'.encode()
    write_log(tmp_path, '2026-10-06', content)
    result = read(tmp_path, lines=2)
    assert result['lines'] == ['вторая', 'третья']
    assert result['read']['reasons'] == ['line_limit']


def test_latest_files_order_search_and_exact_utc_date(tmp_path):
    write_log(tmp_path, '2026-10-03', b'older omitted\n')
    write_log(tmp_path, '2026-10-04', b'first match\n')
    write_log(tmp_path, '2026-10-05', b'second MATCH\n')
    write_log(tmp_path, '2026-10-06', b'latest\n')
    (tmp_path / 'agent_2026-10-05-extra.log').write_bytes(b'not a daily log\n')
    result = read(tmp_path, search='match')
    assert result['lines'] == ['first match', 'second MATCH']
    assert result['read']['files_scanned'] == 3 and result['read']['files_available'] == 4
    assert result['read']['reasons'] == ['file_limit']
    result = read(tmp_path, date='2026-10-05')
    assert result['lines'] == ['second MATCH'] and not result['read']['truncated']


@pytest.mark.parametrize('date', ['2026-02-30', '*', '../secret', '20261006', '2026-W41-2', '2026-1-06'])
def test_date_cannot_expand_file_glob_or_accept_invalid_calendar(tmp_path, date):
    with pytest.raises(ValueError):
        read(tmp_path, date=date)


def test_search_budget_does_not_return_partial_oldest_line(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'SCAN_BYTES', 9)
    monkeypatch.setattr(reader, 'CHUNK_BYTES', 4)
    write_log(tmp_path, '2026-10-06', b'OLD-MATCH\nlast\n')
    result = read(tmp_path, search='MATCH')
    assert result['lines'] == []
    assert result['read']['bytes_scanned'] == 9
    assert result['read']['reasons'] == ['scan_byte_limit']


def test_byte_scan_budget_is_shared_across_files(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'SCAN_BYTES', 12)
    write_log(tmp_path, '2026-10-05', b'old\nolder\n')
    write_log(tmp_path, '2026-10-06', b'new\n')
    result = read(tmp_path)
    assert result['lines'] == ['older', 'new']
    assert result['read']['bytes_scanned'] == 12 and result['read']['files_scanned'] == 2
    assert result['read']['reasons'] == ['scan_byte_limit']


def test_oversized_lines_are_omitted_whole_with_explicit_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'LINE_BYTES', 8)
    monkeypatch.setattr(reader, 'CHUNK_BYTES', 3)
    write_log(tmp_path, '2026-10-06', b'old\n' + b'x' * 200 + b'\nnew\n')
    result = read(tmp_path)
    assert result['lines'] == ['old', 'new']
    assert result['read']['omitted_oversized_lines'] == 1
    assert result['read']['reasons'] == ['oversized_line']


def test_response_budget_counts_json_escaping(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'RESPONSE_BYTES', 16)
    write_log(tmp_path, '2026-10-06', b'old\n\x00\x00\n')
    result = read(tmp_path)
    assert result['lines'] == ['\x00\x00']
    assert len(json.dumps(result['lines'], ensure_ascii=False, separators=(',', ':')).encode()) <= 16
    assert result['read']['response_lines_bytes'] == 16
    assert result['read']['reasons'] == ['response_byte_limit']


def test_invalid_utf8_is_replaced_within_response_budget(tmp_path):
    write_log(tmp_path, '2026-10-06', b'ok\n\xff\n')
    result = read(tmp_path)
    assert result['lines'] == ['ok', '\ufffd']


def test_large_file_requires_only_a_tail_chunk(tmp_path, monkeypatch):
    path = write_log(tmp_path, '2026-10-06', b'old\n')
    with path.open('ab') as stream:
        stream.truncate(50 * 1024 * 1024)
        stream.write(b'\nlatest\n')
    monkeypatch.setattr(Path, 'read_text', lambda *args, **kwargs: pytest.fail('Whole file read'))
    result = read(tmp_path, lines=1)
    assert result['lines'] == ['latest']
    assert result['read']['bytes_scanned'] == reader.CHUNK_BYTES


def test_missing_source_is_measured_empty_but_failed_read_is_unavailable(tmp_path, monkeypatch):
    assert read(tmp_path / 'absent')['lines'] == []
    write_log(tmp_path, '2026-10-06', b'fixture\n')
    monkeypatch.setattr(reader.os, 'open', lambda *args: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(reader.LogReadUnavailable):
        read(tmp_path)


def test_unbounded_catalog_is_rejected_instead_of_arbitrary_latest(tmp_path, monkeypatch):
    monkeypatch.setattr(reader, 'CATALOG_ENTRIES', 2)
    for day in ['2026-10-04', '2026-10-05', '2026-10-06']:
        write_log(tmp_path, day, b'fixture\n')
    with pytest.raises(reader.LogReadUnavailable):
        read(tmp_path)


@pytest.mark.asyncio
async def test_io_does_not_block_loop_and_cancelled_http_keeps_capacity_until_worker_finishes(tmp_path, monkeypatch):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(reader, '_slots', slots)
    entered, finish = threading.Event(), threading.Event()

    def slow(*args, **kwargs):
        entered.set()
        assert finish.wait(3)
        return {'lines': []}

    monkeypatch.setattr(reader, 'read_log_tail', slow)
    task = asyncio.create_task(reader.read_log_tail_async(tmp_path, lines=1, date=None, search=None))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.005)
        assert entered.is_set()  # Event loop continued while the file worker was blocked.
        with pytest.raises(reader.LogReadBusy):
            await reader.read_log_tail_async(tmp_path, lines=1, date=None, search=None)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(reader.LogReadBusy):
            await reader.read_log_tail_async(tmp_path, lines=1, date=None, search=None)
    finally:
        finish.set()
        for _ in range(100):
            if slots.acquire(blocking=False):
                slots.release()
                break
            await asyncio.sleep(0.005)
        else:
            pytest.fail('Read slot did not recover')


@pytest.mark.asyncio
async def test_route_authorizes_before_filesystem_and_reports_failure(monkeypatch):
    router = importlib.import_module('backend.api.v1.logs.router')
    from fastapi import HTTPException

    denied = AsyncMock(side_effect=HTTPException(status_code=404))
    operation = AsyncMock()
    monkeypatch.setattr(router, '_owned_device', denied)
    monkeypatch.setattr(router, 'read_log_tail_async', operation)
    with pytest.raises(HTTPException) as error:
        await router.get_device_logs('foreign', lines=1, date=None, search=None, _principal=object(), db=object())
    assert error.value.status_code == 404
    operation.assert_not_awaited()
    monkeypatch.setattr(router, '_owned_device', AsyncMock())
    for exception in [reader.LogReadBusy(), reader.LogReadUnavailable()]:
        operation.side_effect = exception
        with pytest.raises(HTTPException) as error:
            await router.get_device_logs('owned', lines=1, date=None, search=None, _principal=object(), db=object())
        assert error.value.status_code == 503
