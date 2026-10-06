"""Read-only build preflight: volume health, disk, RAM and Windows commit headroom.

Never deletes caches, changes page files, restarts Docker or sends device commands.
Linux commit accounting differs from Windows; do not compare it to a Windows limit.
"""
from __future__ import annotations

import argparse
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
WINDOWS_MEMORY_COMMAND = """
$ErrorActionPreference = 'Stop'
$osInfo = Get-CimInstance Win32_OperatingSystem
$memoryInfo = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
$volumeInfo = @(Get-Volume -FilePath $env:SPHERE_RESOURCE_GUARD_PATH -ErrorAction Stop)
if ($volumeInfo.Count -ne 1) { throw 'Workspace must resolve to exactly one volume.' }
[pscustomobject]@{
 availableRamBytes=[long]$osInfo.FreePhysicalMemory*1024
 totalRamBytes=[long]$osInfo.TotalVisibleMemorySize*1024
 committedBytes=[long]$memoryInfo.CommittedBytes
 commitLimitBytes=[long]$memoryInfo.CommitLimit
 volumeHealthStatus=[string]$volumeInfo[0].HealthStatus
 volumeOperationalStatus=@($volumeInfo[0].OperationalStatus | ForEach-Object { $_.ToString() })
} | ConvertTo-Json -Compress
"""


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


def collect(path: Path) -> dict:
    snapshot = {"observedAt": datetime.now(timezone.utc).isoformat(),
                "system": platform.system(), "freeDiskBytes": shutil.disk_usage(path).free,
                "deviceCommandsSent": False, "mutationsPerformed": False}
    try:
        if snapshot["system"] == "Windows":
            response = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive",
                                       "-Command", WINDOWS_MEMORY_COMMAND], check=True,
                                      capture_output=True, text=True, timeout=10,
                                      env=os.environ | {"SPHERE_RESOURCE_GUARD_PATH": str(path)})
            if len(response.stdout) > 8192:
                raise ValueError("Oversized memory response")
            data = json.loads(response.stdout.lstrip("\ufeff"))
            if not isinstance(data, dict):
                raise ValueError("Invalid memory response")
            snapshot.update({key: data.get(key) for key in ["availableRamBytes", "totalRamBytes",
                            "committedBytes", "commitLimitBytes", "volumeHealthStatus", "volumeOperationalStatus"]})
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
    args = parser.parse_args()
    snapshot = collect(args.path.resolve(strict=True))
    try:
        snapshot["findings"] = evaluate(snapshot, min_disk_gib=args.min_disk_gib,
                                       min_ram_gib=args.min_ram_gib,
                                       max_commit_percent=args.max_commit_percent)
    except ValueError as error:
        parser.error(str(error))
    snapshot["buildAllowed"] = not snapshot["findings"]
    if args.output:
        write_json(args.output, snapshot)
    print(json.dumps(snapshot))
    return 0 if snapshot["buildAllowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
