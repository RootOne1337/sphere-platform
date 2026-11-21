"""Bounded, metadata-only host disk growth attribution; never cleans/restarts.

Directory sums are logical accessible bytes, not physical disk allocation.
Candidate files are bounded largest files, not a complete file-change journal.
Reports contain private local paths: do not publish raw samples.
"""
from __future__ import annotations

import argparse
import ctypes
import heapq
import json
import os
import platform
import shutil
import stat
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json

MIB = 1024 ** 2
MAX_SAMPLE_BYTES = MIB


def native_path(path: Path | str) -> str:
    """Use extended absolute Windows paths, including UNC, for metadata APIs."""
    text = str(path)
    if platform.system() != 'Windows' or text.startswith('\\\\?\\'):
        return text
    if text.startswith('\\\\'):
        return '\\\\?\\UNC\\' + text[2:]
    return '\\\\?\\' + text


def display_path(path: str) -> Path:
    """Keep report keys comparable to ordinary absolute watch-root paths."""
    if path.startswith('\\\\?\\UNC\\'):
        return Path('\\\\' + path[8:])
    return Path(path.removeprefix('\\\\?\\'))


def reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400)


def allocation(path: Path, info: os.stat_result) -> tuple[int | None, str | None]:
    """Windows sparse/compressed size; missing measurement is not zero."""
    if platform.system() != "Windows":
        blocks = getattr(info, "st_blocks", None)
        return (blocks * 512, None) if blocks is not None else (None, "unsupported")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    measure = kernel.GetCompressedFileSizeW
    measure.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    measure.restype = ctypes.c_uint32
    high = ctypes.c_uint32()
    ctypes.set_last_error(0)
    low = measure(native_path(path), ctypes.byref(high))
    error = ctypes.get_last_error()
    if low == 0xFFFFFFFF and error:
        return None, f"win32_{error}"
    return (high.value << 32) + low, None


def file_state(path: Path) -> dict:
    try:
        info = os.stat(native_path(path), follow_symlinks=False)
        if reparse(info) or not stat.S_ISREG(info.st_mode):
            return {"state": "unavailable", "error": "not_regular_or_reparse"}
        allocated, error = allocation(path, info)
        return {"state": "measured", "logicalBytes": info.st_size,
                "allocatedBytes": allocated, "allocationError": error,
                "modifiedNs": info.st_mtime_ns,
                "identity": [info.st_dev, info.st_ino]}
    except OSError as error:
        return {"state": "unavailable", "error": type(error).__name__}


def scan_root(root: Path, *, excluded: Path, max_entries: int = 500000,
              seconds: float = 60, candidate_limit: int = 2000) -> tuple[dict, dict]:
    """Complete totals or explicit partial/unavailable scope; bounded candidates."""
    started = time.monotonic()
    totals: dict[str, int] = defaultdict(int)
    candidates: list[tuple[int, str, int]] = []
    files = entries_seen = errors = skipped = logical = 0
    error_samples: list[dict[str, str]] = []
    status = "complete"
    try:
        info = os.stat(native_path(root), follow_symlinks=False)
        if reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("root_not_directory_or_reparse")
    except (OSError, ValueError) as error:
        return {"state": "unavailable", "error": type(error).__name__}, {}
    stack = [root]
    while stack:
        if entries_seen >= max_entries or time.monotonic() - started >= seconds:
            status = "partial_budget"
            break
        directory = stack.pop()
        try:
            with os.scandir(native_path(directory)) as entries:
                for entry in entries:
                    if entries_seen >= max_entries or time.monotonic() - started >= seconds:
                        status = "partial_budget"
                        break
                    entries_seen += 1
                    path = display_path(entry.path)
                    if path == excluded or excluded in path.parents:
                        skipped += 1
                        continue
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if reparse(info):
                            skipped += 1
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            stack.append(path)
                        elif stat.S_ISREG(info.st_mode):
                            files += 1
                            logical += info.st_size
                            relative = path.relative_to(root)
                            key = "/".join(relative.parts[:2]) if len(relative.parts) > 2 else (
                                relative.parts[0] if len(relative.parts) > 1 else "[root files]")
                            totals[key] += info.st_size
                            if info.st_size >= MIB:
                                item = (info.st_size, str(relative), info.st_mtime_ns)
                                if len(candidates) < candidate_limit:
                                    heapq.heappush(candidates, item)
                                elif item > candidates[0]:
                                    heapq.heapreplace(candidates, item)
                    except OSError as error:
                        errors += 1
                        if len(error_samples) < 10:
                            error_samples.append({'path': str(path.relative_to(root)), 'type': type(error).__name__})
        except OSError as error:
            errors += 1
            if len(error_samples) < 10:
                error_samples.append({'path': str(directory.relative_to(root)), 'type': type(error).__name__})
    if errors and status == "complete":
        status = "partial_access"
    report = {"state": status, "logicalBytesSeen": logical, "filesSeen": files,
              "entriesSeen": entries_seen, "errors": errors, "skipped": skipped,
              "errorSamples": error_samples,
              "scanSeconds": round(time.monotonic() - started, 3),
              "hardLinksDeduplicated": False, "candidateLimit": candidate_limit,
              "candidateScope": "largest files >=1MiB; candidate membership is not a creation/deletion event",
              "directoryTotals": dict(totals)}
    states = {name: {"logicalBytes": size, "modifiedNs": modified}
              for size, name, modified in candidates}
    return report, states


def changed_files(before: dict, after: dict) -> list[dict]:
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old is None or new is None:
            changes.append({"path": path, "event": "new_to_candidate_set" if old is None else "left_candidate_set",
                            "logicalDeltaBytes": None})
            continue
        if old.get("state", "measured") != "measured" or new.get("state", "measured") != "measured":
            continue
        delta = new["logicalBytes"] - old["logicalBytes"]
        allocated = (new["allocatedBytes"] - old["allocatedBytes"]
                     if old.get("allocatedBytes") is not None and new.get("allocatedBytes") is not None else None)
        if delta or allocated or old.get("identity") != new.get("identity"):
            changes.append({"path": path, "event": "replaced" if old.get("identity") != new.get("identity") else "size_changed",
                            "logicalDeltaBytes": delta, "allocatedDeltaBytes": allocated})
    return sorted(changes, key=lambda item: max(abs(item.get("logicalDeltaBytes") or 0),
                                             abs(item.get("allocatedDeltaBytes") or 0)), reverse=True)


def changed_roots(before: dict, after: dict) -> list[dict]:
    changes = []
    for name, new in after.items():
        old = before.get(name)
        if not old or old["state"] != "complete" or new["state"] != "complete":
            continue
        groups = []
        for path in sorted(set(old["directoryTotals"]) | set(new["directoryTotals"])):
            delta = new["directoryTotals"].get(path, 0) - old["directoryTotals"].get(path, 0)
            if delta:
                groups.append({"path": path, "logicalDeltaBytes": delta})
        changes.append({"root": name, "logicalDeltaBytes": new["logicalBytesSeen"] - old["logicalBytesSeen"],
                        "changedDirectories": sorted(groups, key=lambda item: abs(item['logicalDeltaBytes']), reverse=True)[:20]})
    return changes


def save_sample(output: Path, index: int, report: dict, *, used: int, limit: int) -> int:
    encoded = json.dumps(report, indent=2, ensure_ascii=False).encode()
    if len(encoded) > MAX_SAMPLE_BYTES or used + len(encoded) > limit:
        raise ValueError("report_storage_budget_exceeded")
    write_json(output / f"sample-{index:03d}.json", report)
    return used + len(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append', default=[])
    parser.add_argument('--file', type=Path, action='append', default=[])
    parser.add_argument('--volume', type=Path, default=Path.cwd())
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=97)
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--roots-every', type=int, default=3)
    parser.add_argument('--max-total-mib', type=int, default=16)
    args = parser.parse_args()
    if (not 1 <= args.samples <= 97 or not 60 <= args.interval <= 3600
            or (args.samples - 1) * args.interval > 86400 or not 1 <= args.roots_every <= 60
            or not 1 <= args.max_total_mib <= 32 or not args.root and not args.file
            or len(args.root) > 12 or len(args.file) > 100):
        parser.error('Invalid finite duration, storage budget or watch scope')
    roots = [Path(os.path.abspath(path)) for path in args.root]
    files = [Path(os.path.abspath(path)) for path in args.file]
    if len(set(roots)) != len(roots) or any(a in b.parents for a in roots for b in roots if a != b):
        parser.error('Watched roots must be unique and non-overlapping')
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    previous_files: dict = {}
    previous_roots: dict = {}
    previous_candidates: dict = {}
    previous_free: int | None = None
    used = 0
    status = {'state': 'running', 'samplesWritten': 0, 'pid': os.getpid(),
              'maximumSampleBytes': MAX_SAMPLE_BYTES, 'maximumReportBytes': args.max_total_mib * MIB,
              'fileContentsRead': False, 'targetMutationsPerformed': False,
              'watcherOutputExcludedFromRootScan': True}
    write_json(output / 'status.json', status)
    try:
        for index in range(args.samples):
            started = time.monotonic()
            free_before = shutil.disk_usage(args.volume).free
            if free_before < 512 * MIB:
                status['state'] = 'stopped_low_disk'
                return 2
            watched = {str(path): file_state(path) for path in files}
            root_reports = {}
            candidates = {}
            if index % args.roots_every == 0:
                for root in roots:
                    measured, items = scan_root(root, excluded=output)
                    candidates.update({str(root / path): value for path, value in items.items()})
                    root_reports[str(root)] = measured
            comparable = [Path(name) for name, measured in root_reports.items()
                          if measured['state'] == 'complete'
                          and previous_roots.get(name, {}).get('state') == 'complete']
            old_candidates = {name: value for name, value in previous_candidates.items()
                              if any(root in Path(name).parents for root in comparable)}
            new_candidates = {name: value for name, value in candidates.items()
                              if any(root in Path(name).parents for root in comparable)}
            free_after = shutil.disk_usage(args.volume).free
            report = {'observedAt': datetime.now(timezone.utc).isoformat(), 'sample': index,
                      'freeDiskBytes': free_after, 'freeBeforeScanBytes': free_before,
                      'freeDeltaFromPreviousSample': None if previous_free is None else free_after - previous_free,
                      'watchedFiles': watched, 'watchedFileChanges': changed_files(previous_files, watched)[:50] if index else [],
                      'rootScanIncluded': bool(root_reports), 'roots': root_reports,
                      'rootChanges': changed_roots(previous_roots, root_reports),
                      'candidateChanges': changed_files(old_candidates, new_candidates)[:50],
                      'sampleStorageBytesBefore': used, 'writerProcessAttribution': 'not provided; use scoped OS I/O trace after identifying growth',
                      'fileContentsRead': False, 'targetMutationsPerformed': False}
            used = save_sample(output, index, report, used=used, limit=args.max_total_mib * MIB)
            status.update(samplesWritten=index + 1, reportBytes=used, lastSampleAt=report['observedAt'])
            write_json(output / 'status.json', status)
            previous_files = watched
            if root_reports:
                previous_roots, previous_candidates = root_reports, candidates
            previous_free = free_after
            if index < args.samples - 1:
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
        else:
            status['state'] = 'complete'
    except (OSError, ValueError) as error:
        status.update(state='stopped_error', error=type(error).__name__)
        return 2
    finally:
        status['finishedAt'] = datetime.now(timezone.utc).isoformat()
        write_json(output / 'status.json', status)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
