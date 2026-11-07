"""Read finite disk-growth samples without attributing writes from size alone.

CLI output omits watched paths. Incomplete allocation or changed file identity
cannot become a zero delta. Input snapshots are never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

MAX_SAMPLES = 97
MAX_SAMPLE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 256
SAMPLE_NAME = re.compile(r"sample-(\d{3})\.json\Z")


class FreeDiskChange(TypedDict):
    fromSample: int
    toSample: int
    observedAtUtc: str
    freeDeltaBytes: int


def integer(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f"invalid_{label}")
    return value


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("invalid_timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("timestamp_requires_offset")
    return parsed.astimezone(timezone.utc)


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def load_samples(directory: Path) -> tuple[list[dict], int]:
    root = directory.stat(follow_symlinks=False)
    if not stat.S_ISDIR(root.st_mode) or getattr(root, "st_file_attributes", 0) & 0x400:
        raise ValueError("input_requires_regular_directory")
    selected: list[tuple[int, Path]] = []
    for count, path in enumerate(directory.iterdir(), start=1):
        if count > MAX_ENTRIES:
            raise ValueError("directory_entry_budget")
        match = SAMPLE_NAME.fullmatch(path.name)
        if match:
            selected.append((int(match[1]), path))
    if not 1 <= len(selected) <= MAX_SAMPLES:
        raise ValueError("sample_count_budget")
    samples: list[dict] = []
    total = 0
    for index, path in sorted(selected):
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("sample_requires_regular_file")
        if info.st_size > MAX_SAMPLE_BYTES or total + info.st_size > MAX_TOTAL_BYTES:
            raise ValueError("sample_storage_budget")
        with path.open("rb") as stream:
            payload = stream.read(MAX_SAMPLE_BYTES + 1)
        total += len(payload)
        if len(payload) > MAX_SAMPLE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("sample_storage_budget")
        sample = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_object)
        if not isinstance(sample, dict) or integer(sample.get("sample"), "sample_index") != index:
            raise ValueError("filename_index_mismatch")
        samples.append(sample)
    return samples, total


def summarize(samples: list[dict]) -> dict:
    if not 1 <= len(samples) <= MAX_SAMPLES:
        raise ValueError("sample_count_budget")
    indices = [integer(row.get("sample"), "sample_index") for row in samples]
    times = [timestamp(row.get("observedAt")) for row in samples]
    free = [integer(row.get("freeDiskBytes"), "free_disk") for row in samples]
    for index in range(1, len(samples)):
        if indices[index] <= indices[index - 1] or times[index] <= times[index - 1]:
            raise ValueError("non_increasing_sample_sequence")
    inventories: list[dict] = []
    for row in samples:
        items = row.get("watchedFiles")
        if not isinstance(items, dict) or len(items) > 100:
            raise ValueError("invalid_file_inventory")
        inventories.append(items)
    keys = set().union(*(set(items) for items in inventories))
    if len(keys) > 100 or any(not isinstance(path, str) for path in keys):
        raise ValueError("invalid_file_inventory")
    paths = sorted(keys)
    files = []
    for path in paths:
        rows = [items.get(path, {}) for items in inventories]
        measured = [isinstance(row, dict) and row.get("state") == "measured" for row in rows]
        for row, available in zip(rows, measured, strict=True):
            if available:
                integer(row.get("logicalBytes"), "logical_bytes")
                if row.get("allocatedBytes") is not None:
                    integer(row["allocatedBytes"], "allocated_bytes")
        complete = all(measured)
        identities = [row.get("identity") if available else None
                      for row, available in zip(rows, measured, strict=True)]
        same_identity = complete and all(
            isinstance(identity, list) and len(identity) == 2
            and all(type(part) is int for part in identity)
            and identity != [0, 0]
            and identity == identities[0] for identity in identities)
        logical = [row["logicalBytes"] for row, available in zip(rows, measured, strict=True) if available]
        allocation_complete = complete and all(row.get("allocatedBytes") is not None for row in rows)
        allocated = [row["allocatedBytes"] for row, available in zip(rows, measured, strict=True)
                     if available and row.get("allocatedBytes") is not None]
        files.append({
            "watchId": hashlib.sha256(path.encode("utf-8")).hexdigest(),
            "measuredSamples": sum(measured), "sampleCount": len(samples),
            "sameIdentityThroughout": same_identity,
            "observedLogicalConstant": len(set(logical)) == 1 if complete else None,
            "logicalDeltaBytes": logical[-1] - logical[0] if same_identity else None,
            "logicalConstantThroughout": len(set(logical)) == 1 if same_identity else None,
            "allocationComplete": allocation_complete,
            "allocatedDeltaBytes": allocated[-1] - allocated[0] if same_identity and allocation_complete else None,
            "allocatedConstantThroughout": len(set(allocated)) == 1 if same_identity and allocation_complete else None,
        })
    intervals = [(times[index] - times[index - 1]).total_seconds() for index in range(1, len(times))]
    changes: list[FreeDiskChange] = [{"fromSample": indices[index - 1], "toSample": indices[index],
                "observedAtUtc": times[index].isoformat(), "freeDeltaBytes": free[index] - free[index - 1]}
               for index in range(1, len(free))]
    return {
        "schemaVersion": 1, "sampleCount": len(samples),
        "firstSample": indices[0], "lastSample": indices[-1],
        "missingSequenceIntervals": sum(b != a + 1 for a, b in zip(indices, indices[1:])),
        "startedUtc": times[0].isoformat(), "lastObservedUtc": times[-1].isoformat(),
        "elapsedSeconds": (times[-1] - times[0]).total_seconds(),
        "minimumIntervalSeconds": min(intervals) if intervals else None,
        "maximumIntervalSeconds": max(intervals) if intervals else None,
        "freeStartBytes": free[0], "freeEndBytes": free[-1], "freeDeltaBytes": free[-1] - free[0],
        "largestObservedDrops": sorted((row for row in changes if row["freeDeltaBytes"] < 0),
                                      key=lambda row: row["freeDeltaBytes"])[:10],
        "watchedFiles": files, "writerAttribution": "UNDETERMINED",
        "limitations": ["Endpoints and sample sizes do not identify a process or prove a leak.",
                        "Writes between samples and within fixed-size files remain possible.",
                        "Directory scans, VSS and RAM are outside this report's scope.",
                        "Sequence gaps and unavailable allocation are preserved, not replaced with zero."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        samples, byte_count = load_samples(args.input_dir)
        report = summarize(samples)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        parser.exit(2, f"Disk report rejected: {type(error).__name__}\n")
    report["inputBytesRead"] = byte_count
    report["inputMutationsPerformed"] = False
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
