"""Bounded WinDirStat snapshots for subsequent disk investigations.

WinDirStat performs the scan. This wrapper verifies the installed executable,
limits the child/report lifetime and summarizes its CSV without reading files.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from scripts.pilot.atomic_json import write_json
from scripts.pilot.local_ci import execution_lock
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.windows_ci_job import WindowsChildJob

VERSION = "2.9.3"
EXE_SHA256 = "c6925752fe688aa72115723f23dbb95a7e1c55f094a7d7f30acb5f509a38045b"
OWNED_FILES = {"status.json", "scan.csv", "scan.csv.gz", "summary.json"}
FIELDS = [
    ("Name", "Имя"),
    ("Logical Size", "Логический размер"),
    ("Physical Size", "Физический размер"),
    ("WinDirStat Attributes", "WinDirStat Атрибуты"),
]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def summarize(path: Path, *, producer_complete: bool) -> dict:
    directories, largest, rows, malformed = [], [], 0, 0
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        keys = [
            next((key for key in alternatives if key in headers), None) for alternatives in FIELDS
        ]
        if any(key is None for key in keys):
            raise ValueError("unsupported_export_headers")
        for row in reader:
            try:
                name = row[keys[0]]
                logical, physical = int(row[keys[1]]), int(row[keys[2]])
                kind = int(row[keys[3]], 16) & 0xFF
                if logical < 0 or physical < 0 or not name:
                    raise ValueError("invalid_export_row")
            except (ValueError, TypeError, KeyError):
                malformed += 1
                continue
            rows += 1
            entry = {"path": name, "logicalBytes": logical, "physicalBytes": physical}
            if kind in {2, 4} and len(PureWindowsPath(name).parts) <= 5:
                directories.append(entry)
                if len(directories) > 10000:
                    directories = sorted(
                        directories, key=lambda r: r["physicalBytes"], reverse=True
                    )[:500]
            if kind == 8:
                largest.append(entry)
                if len(largest) > 128:
                    largest = sorted(largest, key=lambda r: r["physicalBytes"], reverse=True)[:32]
    return {
        "source": "WinDirStat " + VERSION,
        "rowsRead": rows,
        "malformedRows": malformed,
        "completeExport": producer_complete and malformed == 0 and rows > 0,
        "accessibleFolders": sorted(directories, key=lambda r: r["physicalBytes"], reverse=True)[
            :60
        ],
        "largestAccessibleFiles": sorted(largest, key=lambda r: r["physicalBytes"], reverse=True)[
            :32
        ],
        "physicalTotalsArePerPath": True,
        "hardlinksMayShareAllocation": True,
        "protectedInaccessibleSpace": "UNKNOWN",
        "writerAttribution": "UNDETERMINED",
    }


def retain(base: Path, *, keep: int = 3) -> None:
    """Only this wrapper's marked, flat, completed snapshot files are eligible."""
    owned = []
    for directory in base.iterdir():
        if directory.is_symlink() or os.name == "nt" and directory.is_junction():
            raise ValueError("snapshot_directory_redirected")
        if not directory.is_dir() or not (directory / "status.json").is_file():
            raise ValueError("snapshot_marker_missing")
        marker = json.loads((directory / "status.json").read_text(encoding="utf-8"))
        if (
            marker.get("producer") != "sphere-windirstat-wrapper"
            or marker.get("state") == "running"
        ):
            raise ValueError("unknown_or_active_snapshot")
        if any(
            f.name not in OWNED_FILES or not f.is_file() or f.is_symlink()
            for f in directory.iterdir()
        ):
            raise ValueError("snapshot_contains_foreign_files")
        owned.append(directory)
    for directory in sorted(owned, key=lambda d: d.name, reverse=True)[keep:]:
        for file in directory.iterdir():
            if file.resolve().parent != directory.resolve():
                raise ValueError("snapshot_file_redirected")
            file.unlink()
        directory.rmdir()


def scan(root: Path, scope: str) -> dict:
    if os.name != "nt" or scope not in {"project", "profile", "system"}:
        raise ValueError("unsupported_scan_scope")
    root = root.resolve(strict=True)
    guard = collect(root)
    if evaluate(guard, min_disk_gib=4, min_ram_gib=3):
        raise ValueError("volume_or_scan_headroom_not_ready")
    exe = root / ".local-pilot/tools/windirstat-2.9.3/x64/WinDirStat.exe"
    if not exe.is_file() or exe.is_symlink() or digest(exe) != EXE_SHA256:
        raise ValueError("verified_windirstat_installation_required")
    targets = {
        "project": root,
        "profile": Path(os.environ["USERPROFILE"]),
        "system": Path(root.anchor),
    }
    base = root / ".local-pilot/disk-scans"
    if base.is_symlink() or base.exists() and base.is_junction():
        raise ValueError("snapshot_root_redirected")
    base.mkdir(exist_ok=True)
    with execution_lock(root / ".local-pilot/disk-scan.lock"):
        retain(base)
        directory = base / (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        )
        directory.mkdir(exist_ok=False)
        csv_file = directory / "scan.csv"
        status = {
            "producer": "sphere-windirstat-wrapper",
            "schemaVersion": 1,
            "state": "running",
            "scope": scope,
            "toolVersion": VERSION,
            "toolSha256": EXE_SHA256,
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "privilegeMode": "caller-token",
            "rawBudgetBytes": 2 * 1024**3,
            "compressedBudgetBytes": 128 * 1024**2,
            "timeoutSeconds": 900,
            "sourceFilesRead": False,
            "targetCleanupPerformed": False,
        }
        write_json(directory / "status.json", status)
        started = time.monotonic()
        process = subprocess.Popen(
            [str(exe), "/SaveTo", str(csv_file), str(targets[scope])],
            cwd=exe.parent,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS,
        )
        job = WindowsChildJob(process, memory_bytes=2 * 1024**3)
        try:
            while process.poll() is None:
                if time.monotonic() - started > status["timeoutSeconds"]:
                    status["state"] = "stopped_deadline"
                    break
                if csv_file.exists() and csv_file.stat().st_size > status["rawBudgetBytes"]:
                    status["state"] = "stopped_output_budget"
                    break
                if shutil.disk_usage(root).free < 3 * 1024**3:
                    status["state"] = "stopped_low_disk"
                    break
                time.sleep(1)
            if status["state"] == "running":
                status["state"] = (
                    "exported" if process.returncode == 0 and csv_file.exists() else "export_failed"
                )
        finally:
            job.close()
            process.wait(timeout=15)
            status.update(
                exitCode=process.returncode, elapsedSeconds=round(time.monotonic() - started, 3)
            )
            write_json(directory / "status.json", status)
        if csv_file.exists():
            summary = summarize(csv_file, producer_complete=status["state"] == "exported")
            write_json(directory / "summary.json", summary)
            status["rawCsvSha256"] = digest(csv_file)
            packed = directory / "scan.csv.gz"
            with csv_file.open("rb") as source, gzip.open(packed, "wb", compresslevel=1) as dest:
                shutil.copyfileobj(source, dest, length=1024 * 1024)
            status["compressedBytes"] = packed.stat().st_size
            if status["compressedBytes"] <= status["compressedBudgetBytes"]:
                with gzip.open(packed, "rb") as source:
                    hasher = hashlib.sha256()
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        hasher.update(chunk)
                if hasher.hexdigest() != status["rawCsvSha256"]:
                    raise ValueError("compressed_snapshot_integrity_failed")
                csv_file.unlink()
            else:
                status["state"] = "compressed_budget_exceeded"
                packed.unlink()
                csv_file.unlink()
                status["fullSnapshotRetained"] = False
                status["summaryRetained"] = True
        status["finishedAt"] = datetime.now(timezone.utc).isoformat()
        write_json(directory / "status.json", status)
        retain(base)
        return status | {"reportDirectory": str(directory.relative_to(root))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=["project", "profile", "system"], default="project")
    args = parser.parse_args()
    result = scan(Path(__file__).resolve().parents[2], args.scope)
    print(json.dumps(result))
    return 0 if result["state"] == "exported" else 2


if __name__ == "__main__":
    raise SystemExit(main())
