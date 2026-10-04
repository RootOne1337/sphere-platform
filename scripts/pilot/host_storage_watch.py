"""Finite Windows disk/VSS/RAM observation; metadata only, no cleanup or restarts.

Private reports include paths and process names. They are not publication artifacts.
Process IO includes network traffic and is not evidence of persistent disk growth.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.disk_growth import changed_files, file_state, reparse

MIB = 1024 ** 2
SAMPLE_LIMIT = 128 * 1024
STATUS_ALLOWANCE = 32 * 1024
HOST_COMMAND = r"""
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$osInfo=Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 5
$memory=Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory -OperationTimeoutSec 5
$vssState='measured'; $vss=@(); $vssError=$null
try {
    $vss=@(Get-CimInstance Win32_ShadowStorage -OperationTimeoutSec 5 | ForEach-Object {
        if ($null -eq $_.UsedSpace -or $null -eq $_.AllocatedSpace -or $null -eq $_.MaxSpace) { throw 'Incomplete counters' }
        [pscustomobject]@{volume=$_.Volume.CimInstanceProperties['DeviceID'].Value;
            diffVolume=$_.DiffVolume.CimInstanceProperties['DeviceID'].Value;
            usedBytes=[long]$_.UsedSpace;allocatedBytes=[long]$_.AllocatedSpace;maxBytes=[long]$_.MaxSpace}
    })
} catch { $vssState='unavailable'; $vss=@(); $vssError=$_.Exception.GetType().Name }
$processes=@(Get-Process | Sort-Object PrivateMemorySize64 -Descending | Select-Object -First 32 | ForEach-Object {
    $started=$null
    try {$started=$_.StartTime.ToUniversalTime().ToString('o')} catch {}
    [pscustomobject]@{pid=$_.Id;name=$_.ProcessName;startedAt=$started;
        privateBytes=$_.PrivateMemorySize64;workingSetBytes=$_.WorkingSet64}
})
$io=@(Get-CimInstance Win32_PerfFormattedData_PerfProc_Process -OperationTimeoutSec 5 |
    Where-Object {$_.Name -notin @('_Total','Idle')} | Sort-Object IOWriteBytesPersec -Descending |
    Select-Object -First 16 Name,IDProcess,IOWriteBytesPersec)
$pagefiles=@(Get-CimInstance Win32_PageFileUsage -OperationTimeoutSec 5 |
    Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage)
[pscustomobject]@{bootUtc=$osInfo.LastBootUpTime.ToUniversalTime().ToString('o');
    availableRamBytes=[long]$osInfo.FreePhysicalMemory*1024;totalRamBytes=[long]$osInfo.TotalVisibleMemorySize*1024;
    committedBytes=[long]$memory.CommittedBytes;commitLimitBytes=[long]$memory.CommitLimit;
    pagedPoolBytes=[long]$memory.PoolPagedBytes;nonpagedPoolBytes=[long]$memory.PoolNonpagedBytes;
    vss=[pscustomobject]@{state=$vssState;rows=$vss;errorType=$vssError};
    processes=$processes;processIoRates=$io;processIoIncludesNonFileTraffic=$true;
    pagefilesMiB=$pagefiles} | ConvertTo-Json -Depth 5 -Compress
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def native(args: list[str], *, timeout: int = 25, limit: int = SAMPLE_LIMIT) -> dict:
    """Known bounded metadata commands only; never persist stderr or command lines."""
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or len(result.stdout) > limit:
            return {'state': 'unavailable', 'exitCode': result.returncode,
                    'errorType': 'output_budget' if len(result.stdout) > limit else 'native_error'}
        return {'state': 'measured', 'output': result.stdout.decode('utf-8-sig')}
    except (OSError, UnicodeError, subprocess.SubprocessError) as error:
        return {'state': 'unavailable', 'errorType': type(error).__name__}


def json_probe(args: list[str], *, lines: bool = False) -> dict:
    result = native(args)
    if result['state'] != 'measured':
        return result
    try:
        value = ([json.loads(line) for line in result['output'].splitlines() if line.strip()]
                 if lines else json.loads(result['output']))
        return {'state': 'measured', 'value': value}
    except (ValueError, TypeError) as error:
        return {'state': 'unavailable', 'errorType': type(error).__name__}


def validate_window(samples: int, interval: int, docker_every: int, budget_mib: int) -> None:
    if not 2 <= samples <= 721 or not 60 <= interval <= 600:
        raise ValueError('Samples must be 2..721; interval must be 60..600 seconds')
    if (samples - 1) * interval > 86400:
        raise ValueError('Observation must finish within 24 hours')
    if not 1 <= docker_every <= 60 or not 1 <= budget_mib <= 32:
        raise ValueError('Docker cadence 1..60 and report budget 1..32 MiB required')


def encode_sample(sample: dict, used: int, budget: int) -> bytes:
    encoded = (json.dumps(sample, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    if len(encoded) > SAMPLE_LIMIT or used + len(encoded) + STATUS_ALLOWANCE > budget:
        raise ValueError('Report budget exceeded; existing evidence retained')
    return encoded


def trend(previous: dict | None, current: dict) -> dict:
    """Only comparable exact measurements yield deltas; IO is not attribution."""
    if previous is None:
        return {'state': 'baseline'}
    result = {'freeDiskDeltaBytes': current['freeDiskBytes'] - previous['freeDiskBytes'],
              'fileChanges': changed_files(previous['files'], current['files']),
              'writerAttribution': 'UNDETERMINED'}
    old, new = previous['host'], current['host']
    if (old.get('state') == new.get('state') == 'measured'
            and isinstance(old['value'].get('bootUtc'), str) and old['value']['bootUtc']
            and old['value'].get('bootUtc') == new['value'].get('bootUtc')):
        for key in ['committedBytes', 'availableRamBytes', 'pagedPoolBytes', 'nonpagedPoolBytes']:
            a, b = old['value'].get(key), new['value'].get(key)
            if type(a) is int and type(b) is int:
                result[key + 'Delta'] = b - a
        old_vss, new_vss = old['value'].get('vss', {}), new['value'].get('vss', {})
        if old_vss.get('state') == new_vss.get('state') == 'measured':
            before = {(r['volume'], r['diffVolume']): r for r in old_vss['rows']}
            result['vssDeltas'] = [dict(volume=r['volume'], diffVolume=r['diffVolume'],
                allocatedDeltaBytes=r['allocatedBytes'] - before[(r['volume'], r['diffVolume'])]['allocatedBytes'],
                usedDeltaBytes=r['usedBytes'] - before[(r['volume'], r['diffVolume'])]['usedBytes'])
                for r in new_vss['rows'] if (r['volume'], r['diffVolume']) in before]
            result['vssMembershipChanged'] = set(before) != {(r['volume'], r['diffVolume']) for r in new_vss['rows']}
    return result


def collect(files: list[Path], docker: bool) -> dict:
    sample = {'observedAt': now(), 'freeDiskBytes': shutil.disk_usage('C:\\').free,
              'files': {str(path): file_state(path) for path in files},
              'host': json_probe(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', HOST_COMMAND])}
    if docker:
        sample['dockerDf'] = json_probe(['docker', 'system', 'df', '--format', '{{json .}}'], lines=True)
        sample['containerStats'] = json_probe(['docker', 'stats', '--no-stream', '--format', '{{json .}}'], lines=True)
        identities = native(['docker', 'ps', '-aq', '--no-trunc'])
        ids = identities.get('output', '').splitlines()
        if (identities['state'] == 'measured' and len(ids) <= 200
                and all(len(item) == 64 and all(c in '0123456789abcdef' for c in item) for item in ids)):
            sample['containerEpochs'] = (native(['docker', 'inspect', '--format',
                '{{.Id}}\t{{.Name}}\t{{.Image}}\t{{.State.Status}}\t{{.State.StartedAt}}', *ids])
                if ids else {'state': 'measured', 'output': ''})
        else:
            sample['containerEpochs'] = {'state': 'unavailable', 'errorType': 'inventory_unavailable_or_budget'}
        sample['dockerGuestDfKiB'] = native(['wsl.exe', '-d', 'docker-desktop', '--', 'df', '-k',
                                           '/mnt/docker-desktop-disk/data'])
        sample['linuxMemoryKiB'] = native(['wsl.exe', '-d', 'docker-desktop', '--', 'cat', '/proc/meminfo'])
    else:
        sample['dockerState'] = 'not_sampled_this_cycle'
    return sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--watch-file', type=Path, action='append', default=[])
    parser.add_argument('--samples', type=int, default=241)
    parser.add_argument('--interval', type=int, default=120)
    parser.add_argument('--docker-every', type=int, default=8)
    parser.add_argument('--max-report-mib', type=int, default=16)
    args = parser.parse_args()
    try:
        validate_window(args.samples, args.interval, args.docker_every, args.max_report_mib)
        if platform.system() != 'Windows' or not ctypes.windll.shell32.IsUserAnAdmin():
            raise ValueError('Dedicated elevated Windows collector required; nothing started')
        if len(args.watch_file) > 100 or len(set(args.watch_file)) != len(args.watch_file):
            raise ValueError('At most 100 distinct absolute named files')
        if any(not path.is_absolute() for path in args.watch_file):
            raise ValueError('Watched paths must be absolute')
        output = args.output_dir.resolve()
        base = Path(__file__).resolve().parents[2] / '.local-pilot'
        if reparse(base.stat(follow_symlinks=False)) or output.parent != base.resolve():
            raise ValueError('New direct report directory must be inside workspace .local-pilot')
        output.mkdir(exist_ok=False)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    started = datetime.now(timezone.utc)
    duration = (args.samples - 1) * args.interval
    status = {'state': 'running', 'pid': os.getpid(), 'administrator': True,
              'startedUtc': started.isoformat(), 'dueUtc': (started + timedelta(seconds=duration)).isoformat(),
              'samplesLimit': args.samples, 'samplesWritten': 0, 'intervalSeconds': args.interval,
              'dockerEverySamples': args.docker_every, 'reportBudgetBytes': args.max_report_mib * MIB,
              'sampleLimitBytes': SAMPLE_LIMIT, 'reportBytes': 0,
              'cleanupPerformed': False, 'deviceCommandsSent': False, 'autostartConfigured': False,
              'fullDirectoryScans': False, 'processIoIsWriterAttribution': False,
              'sourceSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    status_path = output / 'status.json'
    previous = None
    timer = time.monotonic()
    try:
        write_json(status_path, status)
        with (output / 'samples.jsonl').open('xb', buffering=0) as stream:
            for index in range(args.samples):
                if index:
                    time.sleep(max(0, timer + index * args.interval - time.monotonic()))
                if time.monotonic() - timer > duration + args.interval:
                    status['state'] = 'stopped_deadline'
                    break
                sample = collect(args.watch_file, index % args.docker_every == 0 or index == args.samples - 1)
                sample['index'] = index
                sample['trend'] = trend(previous, sample)
                encoded = encode_sample(sample, status['reportBytes'], status['reportBudgetBytes'])
                stream.write(encoded)
                status.update(samplesWritten=index + 1, reportBytes=status['reportBytes'] + len(encoded),
                              lastSampleUtc=sample['observedAt'], freeDiskBytes=sample['freeDiskBytes'])
                write_json(status_path, status)
                previous = sample
                if sample['freeDiskBytes'] < 512 * MIB:
                    status['state'] = 'stopped_low_disk'
                    break
            else:
                status['state'] = 'complete'
    except (OSError, ValueError, KeyError, TypeError) as error:
        status.update(state='stopped_error', errorType=type(error).__name__)
    except KeyboardInterrupt:
        status['state'] = 'interrupted'
    finally:
        status['finishedUtc'] = now()
        write_json(status_path, status)
    print(json.dumps(status))
    return 0 if status['state'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
