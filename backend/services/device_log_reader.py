"""Bounded recent log tails; no history deletion or unbounded work queue."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from datetime import date as Date
from pathlib import Path

SCAN_BYTES = 2 * 1024 * 1024
RESPONSE_BYTES = 512 * 1024
LINE_BYTES = 16 * 1024
CHUNK_BYTES = 64 * 1024
MAX_FILES = 3
CATALOG_ENTRIES = 128
CONCURRENT_READS = 4
_FILE_NAME = re.compile(r"agent_(\d{4}-\d{2}-\d{2})\.log\Z")
_slots = threading.BoundedSemaphore(CONCURRENT_READS)
_executor = ThreadPoolExecutor(max_workers=CONCURRENT_READS, thread_name_prefix="sphere-log-read")


class LogReadBusy(Exception):
    pass


class LogReadUnavailable(Exception):
    pass


def validate_date(value: str | None) -> None:
    if value is not None and (len(value) != 10 or Date.fromisoformat(value).isoformat() != value):
        raise ValueError("Date must use YYYY-MM-DD")


@dataclass
class _Budget:
    scanned: int = 0
    files_scanned: int = 0
    omitted: int = 0
    reasons: set[str] = field(default_factory=set)


def _files(directory: Path, date: str | None) -> tuple[list[Path], int]:
    if directory.is_symlink():
        raise LogReadUnavailable()
    found = []
    try:
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= CATALOG_ENTRIES:
                    # A partial unordered directory cannot certify the newest files.
                    raise LogReadUnavailable()
                match = _FILE_NAME.fullmatch(entry.name)
                if match and (date is None or match[1] == date):
                    if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                        raise LogReadUnavailable()
                    found.append(Path(entry.path))
    except FileNotFoundError:
        return [], 0
    except OSError as exc:
        raise LogReadUnavailable() from exc
    return sorted(found, reverse=True)[:MAX_FILES], len(found)


def _reverse_lines(path: Path, budget: _Budget) -> Generator[bytes, None, None]:
    """Carry at most one bounded line; discard cut/oversized lines, never fragments."""
    carry = b""
    dropping = False
    trailing = True
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if path.is_symlink():
        raise LogReadUnavailable()
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            position = stream.seek(0, os.SEEK_END)
            budget.files_scanned += 1
            while position > 0:
                available = SCAN_BYTES - budget.scanned
                if available <= 0:
                    budget.reasons.add("scan_byte_limit")
                    return
                size = min(position, CHUNK_BYTES, available)
                position -= size
                stream.seek(position)
                chunk = stream.read(size)
                budget.scanned += len(chunk)
                if len(chunk) != size:
                    # Truncation/rotation during this open read is not an empty archive.
                    raise LogReadUnavailable()
                end = len(chunk)
                while (delimiter := chunk.rfind(b"\n", 0, end)) >= 0:
                    suffix = chunk[delimiter + 1:end]
                    if dropping or len(suffix) + len(carry) > LINE_BYTES:
                        budget.omitted += 1
                        budget.reasons.add("oversized_line")
                    else:
                        line = suffix + carry
                        if not (trailing and not line):
                            yield line.removesuffix(b"\r")
                    trailing = False
                    carry, dropping = b"", False
                    end = delimiter
                prefix = chunk[:end]
                if not dropping and len(prefix) + len(carry) <= LINE_BYTES:
                    carry = prefix + carry
                else:
                    carry, dropping = b"", True
            if dropping:
                budget.omitted += 1
                budget.reasons.add("oversized_line")
            elif carry or not trailing:
                yield carry.removesuffix(b"\r")
    except OSError as exc:
        raise LogReadUnavailable() from exc


def read_log_tail(directory: Path, *, lines: int, date: str | None, search: str | None) -> dict:
    validate_date(date)
    if not 1 <= lines <= 10000 or (search is not None and len(search) > 512):
        raise ValueError("Invalid log query budget")
    files, total_files = _files(directory, date)
    budget = _Budget()
    if total_files > len(files):
        budget.reasons.add("file_limit")
    result: list[str] = []
    encoded_bytes = 2  # JSON array delimiters; item separators are included below.
    needle = search.lower() if search else None
    stop = False
    for path in files:
        iterator = _reverse_lines(path, budget)
        try:
            for raw in iterator:
                line = raw.decode("utf-8", errors="replace")
                if needle and needle not in line.lower():
                    continue
                size = len(json.dumps(line, ensure_ascii=False).encode("utf-8")) + (1 if result else 0)
                if encoded_bytes + size > RESPONSE_BYTES:
                    budget.reasons.add("response_byte_limit")
                    stop = True
                    break
                encoded_bytes += size
                result.append(line)
                if len(result) >= lines:
                    budget.reasons.add("line_limit")
                    stop = True
                    break
        finally:
            iterator.close()  # Close the descriptor even on early output/search stop.
        if stop:
            break
        if budget.scanned >= SCAN_BYTES:
            if budget.files_scanned < len(files):
                budget.reasons.add("scan_byte_limit")
            break
    result.reverse()
    return {"lines": result, "total": len(result), "read": {
        "schema_version": 1, "scope": "recent-file-tail", "date": date,
        "truncated": bool(budget.reasons), "reasons": sorted(budget.reasons),
        "bytes_scanned": budget.scanned, "scan_byte_limit": SCAN_BYTES,
        "response_lines_bytes": encoded_bytes, "response_byte_limit": RESPONSE_BYTES,
        "max_line_bytes": LINE_BYTES, "omitted_oversized_lines": budget.omitted,
        "files_scanned": budget.files_scanned, "files_available": total_files, "max_files": MAX_FILES,
        "concurrent_reads_per_worker": CONCURRENT_READS,
    }}


async def read_log_tail_async(directory: Path, *, lines: int, date: str | None, search: str | None) -> dict:
    slots = _slots
    if not slots.acquire(blocking=False):
        raise LogReadBusy()
    try:
        context = copy_context()
        future = _executor.submit(context.run, read_log_tail, directory, lines=lines, date=date, search=search)
    except BaseException:
        slots.release()
        raise
    # Release on actual worker completion (or queued cancellation), not HTTP cancellation.
    future.add_done_callback(lambda completed: slots.release())
    return await asyncio.wrap_future(future)
