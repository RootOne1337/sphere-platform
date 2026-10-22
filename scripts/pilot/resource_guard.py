"""Read-only build preflight: volume health, disk, RAM and Windows commit headroom.

Never deletes caches, changes page files, restarts Docker or sends device commands.
Linux commit accounting differs from Windows; do not compare it to a Windows limit.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json

GIB = 1024 ** 3
WINDOWS_VOLUME_COMMAND = """
$ErrorActionPreference = 'Stop'
$volumeInfo = @(Get-Volume -FilePath $env:SPHERE_RESOURCE_GUARD_PATH -ErrorAction Stop)
if ($volumeInfo.Count -ne 1) { throw 'Workspace must resolve to exactly one volume.' }
[pscustomobject]@{
 volumeHealthStatus=[string]$volumeInfo[0].HealthStatus
 volumeOperationalStatus=@($volumeInfo[0].OperationalStatus | ForEach-Object { $_.ToString() })
} | ConvertTo-Json -Compress
"""


class WindowsPerformanceInfo(ctypes.Structure):
    """Win32 PERFORMANCE_INFORMATION: DWORD is 32 bits, SIZE_T pointer-sized."""

    _fields_ = ([('cb', ctypes.c_uint32)] + [
        (name, ctypes.c_size_t) for name in (
            'CommitTotal', 'CommitLimit', 'CommitPeak', 'PhysicalTotal',
            'PhysicalAvailable', 'SystemCache', 'KernelTotal', 'KernelPaged',
            'KernelNonpaged', 'PageSize',
        )
    ] + [(name, ctypes.c_uint32) for name in ('HandleCount', 'ProcessCount', 'ThreadCount')])


def windows_memory() -> dict[str, int]:
    """Read system-wide counters without launching another measurement process.

    Microsoft maps CommitTotal/CommitLimit to Committed Bytes/Commit Limit.
    All memory fields are pages, converted using the returned PageSize.
    learn.microsoft.com/windows/win32/memory/memory-performance-information
    """
    try:
        query = ctypes.WinDLL('psapi.dll', use_last_error=True, winmode=0x800).GetPerformanceInfo
    except (OSError, AttributeError):
        raise OSError('Windows memory counters unavailable') from None
    query.argtypes = [ctypes.POINTER(WindowsPerformanceInfo), ctypes.c_uint32]
    query.restype = ctypes.c_int
    info = WindowsPerformanceInfo()
    info.cb = ctypes.sizeof(info)
    if not query(ctypes.byref(info), info.cb) or not info.PageSize:
        raise OSError('Windows memory counters unavailable')
    return {name: int(getattr(info, field)) * info.PageSize for name, field in (
        ('availableRamBytes', 'PhysicalAvailable'), ('totalRamBytes', 'PhysicalTotal'),
        ('committedBytes', 'CommitTotal'), ('commitLimitBytes', 'CommitLimit'),
    )}


def integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def evaluate(snapshot: dict, *, min_disk_gib: float = 20, min_ram_gib: float = 4,
             max_commit_percent: float = 85) -> list[str]:
    """Missing/invalid measurements cannot grant permission for a heavy build."""
    if (not math.isfinite(min_disk_gib) or min_disk_gib <= 0
            or not math.isfinite(min_ram_gib) or min_ram_gib <= 0
            or not math.isfinite(max_commit_percent) or not 0 < max_commit_percent < 100):
        raise ValueError("Invalid resource thresholds")
    findings = []
    disk = snapshot.get("freeDiskBytes")
    if not integer(disk):
        findings.append("disk_measurement_unavailable")
    elif disk < min_disk_gib * GIB:
        findings.append("disk_headroom_low")
    ram, total = snapshot.get("availableRamBytes"), snapshot.get("totalRamBytes")
    if not integer(ram) or not integer(total) or total == 0 or ram > total:
        findings.append("memory_measurement_unavailable")
    elif ram < min_ram_gib * GIB:
        findings.append("ram_headroom_low")
    system = snapshot.get("system")
    if system == "Windows":
        used, limit = snapshot.get("committedBytes"), snapshot.get("commitLimitBytes")
        if not integer(used) or not integer(limit) or limit == 0 or used > limit:
            findings.append("commit_measurement_unavailable")
        elif used * 100 >= max_commit_percent * limit:
            findings.append("commit_headroom_low")
        health, operations = snapshot.get("volumeHealthStatus"), snapshot.get("volumeOperationalStatus")
        if (not isinstance(health, str) or not health
                or not isinstance(operations, list) or not operations
                or any(not isinstance(s, str) or not s for s in operations)):
            findings.append("volume_health_unavailable")
        elif health != "Healthy" or operations != ["OK"]:
            findings.append("volume_not_ready")
    elif system != "Linux":
        findings.append("unsupported_host")
    return findings


def admitted_findings(findings: list[str], *, allow_degraded_volume: bool = False) -> list[str]:
    """An explicit operator exception waives only a measured volume warning.

    Keep the original findings in the operation receipt. Missing measurements,
    disk/RAM/commit pressure and source/artifact integrity are never waived.
    This is per invocation; it does not change the collector or scheduled jobs.
    """
    if not isinstance(allow_degraded_volume, bool):
        raise ValueError("Volume exception must be an explicit boolean")
    return [finding for finding in findings
            if not (allow_degraded_volume and finding == "volume_not_ready")]


def collect(path: Path) -> dict:
    snapshot = {"observedAt": datetime.now(timezone.utc).isoformat(),
                "system": platform.system(), "freeDiskBytes": shutil.disk_usage(path).free,
                "deviceCommandsSent": False, "mutationsPerformed": False}
    try:
        if snapshot["system"] == "Windows":
            response = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                       "-Command", WINDOWS_VOLUME_COMMAND], check=True,
                                      capture_output=True, text=True, timeout=10,
                                      env=os.environ | {"SPHERE_RESOURCE_GUARD_PATH": str(path)})
            if len(response.stdout) > 8192:
                raise ValueError("Oversized memory response")
            data = json.loads(response.stdout.lstrip("\ufeff"))
            if not isinstance(data, dict):
                raise ValueError("Invalid memory response")
            snapshot.update({key: data.get(key) for key in ["volumeHealthStatus", "volumeOperationalStatus"]})
            # Measure once, after the short-lived volume probe exits. Measuring
            # inside its CIM/PowerShell process includes avoidable probe overhead.
            # A failed native read remains unavailable; never reuse old values.
            snapshot.update(windows_memory())
            snapshot['memoryMeasurement'] = 'GetPerformanceInfo'
        elif snapshot["system"] == "Linux":
            values = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                if key in {"MemTotal", "MemAvailable"}:
                    values[key] = int(value.split()[0]) * 1024
            snapshot.update(totalRamBytes=values.get("MemTotal"),
                            availableRamBytes=values.get("MemAvailable"))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        # Do not print arbitrary process output, command lines or environment.
        snapshot["collectionError"] = type(error).__name__
    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-disk-gib", type=float, default=20)
    parser.add_argument("--min-ram-gib", type=float, default=4)
    parser.add_argument("--max-commit-percent", type=float, default=85)
    parser.add_argument("--allow-degraded-volume", action="store_true",
                        help="Explicit operator exception for a measured volume warning only")
    args = parser.parse_args()
    snapshot = collect(args.path.resolve(strict=True))
    try:
        snapshot["findings"] = evaluate(snapshot, min_disk_gib=args.min_disk_gib,
                                       min_ram_gib=args.min_ram_gib,
                                       max_commit_percent=args.max_commit_percent)
    except ValueError as error:
        parser.error(str(error))
    snapshot["admissionFindings"] = admitted_findings(
        snapshot["findings"], allow_degraded_volume=args.allow_degraded_volume)
    snapshot["volumeExceptionRequested"] = args.allow_degraded_volume
    snapshot["volumeExceptionApplied"] = args.allow_degraded_volume and "volume_not_ready" in snapshot["findings"]
    snapshot["buildAllowed"] = not snapshot["admissionFindings"]
    if args.output:
        write_json(args.output, snapshot)
    print(json.dumps(snapshot))
    return 0 if snapshot["buildAllowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
