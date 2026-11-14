"""Finite event-triggered kernel captures from the existing host observer.

Administrator required. No cleanup, quota changes, autostart or device commands.
Private ETL reports contain process names and file paths, not file contents.
This is post-trigger capture: it cannot recover writes before its recording starts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.disk_growth import reparse
from scripts.pilot.host_storage_watch import SAMPLE_LIMIT, privilege_mode

MIB = 1024 ** 2
METADATA_LIMIT = MIB
TRACE_ACCOUNTING_LIMIT = 512 * MIB


def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError('UTC timestamp required')
    return parsed


def strict_object(items: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def read_latest(path: Path) -> dict:
    """Read at most two sample bounds; tolerate a partial concurrent last append."""
    if reparse(path.stat(follow_symlinks=False)) or not path.is_file():
        raise ValueError('Regular non-reparse sample file required')
    with path.open('rb') as stream:
        stream.seek(0, os.SEEK_END)
        length = stream.tell()
        offset = max(0, length - 2 * SAMPLE_LIMIT)
        stream.seek(offset)
        data = stream.read(2 * SAMPLE_LIMIT)
    if offset:
        data = data.partition(b'\n')[2]
    complete = data.rsplit(b'\n', 1)[0] if b'\n' in data else b''
    line = complete.rsplit(b'\n', 1)[-1]
    if not line or len(line) >= SAMPLE_LIMIT:
        raise ValueError('No bounded complete sample available')
    value = json.loads(line, object_pairs_hook=strict_object)
    if not isinstance(value, dict):
        raise ValueError('Sample object required')
    return value


@dataclass(frozen=True)
class Observation:
    at: datetime
    free: int
    boot: str | None
    vss: dict[tuple[str, str], tuple[int, int]] | None


def observation(sample: dict, now: datetime) -> Observation:
    at = utc(sample['observedAt'])
    if not 0 <= (now - at).total_seconds() <= 360:
        raise ValueError('Future or stale sample; no capture started')
    free = sample['freeDiskBytes']
    if type(free) is not int or free < 0:
        raise ValueError('Exact free-space counter required')
    host = sample.get('host', {})
    value = host.get('value', {}) if host.get('state') == 'measured' else {}
    boot = value.get('bootUtc')
    if boot is not None:
        utc(boot)
    vss = value.get('vss', {})
    rows = None
    if vss.get('state') == 'measured':
        if not isinstance(vss.get('rows'), list) or len(vss['rows']) > 32:
            raise ValueError('Bounded VSS rows required')
        rows = {}
        for row in vss['rows']:
            key = (row['volume'], row['diffVolume'])
            allocated, maximum = row['allocatedBytes'], row['maxBytes']
            if (not all(isinstance(item, str) and item for item in key)
                    or key in rows or type(allocated) is not int or allocated < 0
                    or type(maximum) is not int or maximum < 0):
                raise ValueError('Invalid/duplicate VSS identity or counter')
            rows[key] = (allocated, maximum)
    return Observation(at, free, boot, rows)


@dataclass
class Trigger:
    threshold: int
    previous: Observation | None = None
    peak_free: int = 0
    vss_peak: dict[tuple[str, str], int] = field(default_factory=dict)
    vss_known: dict[tuple[str, str], tuple[int, int]] | None = None

    def inspect(self, current: Observation) -> list[str]:
        if self.previous and current.at <= self.previous.at:
            return []
        reasons = []
        if self.previous is None or current.boot != self.previous.boot:
            self.peak_free = current.free
            self.vss_peak.clear()
            self.vss_known = None
        self.peak_free = max(self.peak_free, current.free)
        if self.peak_free - current.free >= self.threshold:
            reasons.append('free_space_drop')
        if current.vss is not None and current.boot is not None:
            if self.vss_known is not None:
                if set(current.vss) != set(self.vss_known):
                    reasons.append('vss_membership_changed')
                for key, (allocated, maximum) in current.vss.items():
                    if key in self.vss_known and maximum != self.vss_known[key][1]:
                        reasons.append('vss_quota_changed')
                    baseline = self.vss_peak.get(key, allocated)
                    if allocated - baseline >= self.threshold:
                        reasons.append('vss_allocation_growth')
            for key, (allocated, _) in current.vss.items():
                self.vss_peak[key] = min(self.vss_peak.get(key, allocated), allocated)
            self.vss_known = current.vss
        self.previous = current
        return sorted(set(reasons))

    def rearm(self, current: Observation) -> None:
        self.peak_free = current.free
        self.vss_peak = ({key: value[0] for key, value in current.vss.items()}
                         if current.vss is not None else {})


def run_capture(workspace: Path, duration: int) -> dict:
    executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    script = workspace / 'scripts/pilot/collect_disk_writer.ps1'
    child = subprocess.Popen([str(executable), '-NoProfile', '-NonInteractive', '-File', str(script),
        '-DurationSeconds', str(duration), '-IntervalSeconds', '10', '-StopAfterDropMiB', '128'],
        cwd=workspace, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        stdout, stderr = child.communicate(timeout=duration + 240)
    except subprocess.TimeoutExpired:
        # Do not kill PowerShell during its finally/owned-WPR-stop block. Stop
        # this supervisor and report the exact child PID for manual inspection.
        return {'state': 'unknown_child_timeout', 'pid': child.pid, 'childKilled': False}
    if len(stdout) + len(stderr) > SAMPLE_LIMIT:
        return {'state': 'unknown_output_budget', 'pid': child.pid, 'exitCode': child.returncode}
    records = []
    for line in stdout.decode('utf-8-sig').splitlines():
        if line.startswith('{'):
            records.append(json.loads(line, object_pairs_hook=strict_object))
    if not records:
        return {'state': 'failed_no_status', 'pid': child.pid, 'exitCode': child.returncode}
    status = records[-1]
    report = Path(status['reportDirectory'])
    base = workspace / '.local-pilot'
    if (report.parent != base or not report.name.startswith('disk-writer-')
            or reparse(report.stat(follow_symlinks=False))):
        raise ValueError('Child report escaped owned report root')
    return {'state': status['state'], 'pid': child.pid, 'exitCode': child.returncode,
            'reportDirectory': str(report), 'traceBytes': status.get('traceBytes', 0),
            'instance': status.get('instance'), 'traceStarted': status.get('traceStarted', False),
            'exitReason': status.get('exitReason'), 'sourceSha256': hashlib.sha256(script.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--hours', type=float, default=8)
    parser.add_argument('--max-captures', type=int, default=4)
    parser.add_argument('--drop-mib', type=int, default=128)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[2]
    base = workspace / '.local-pilot'
    try:
        privilege_mode(allow_unprivileged=False)
        if not 0.25 <= args.hours <= 24 or not 1 <= args.max_captures <= 4 or not 32 <= args.drop_mib <= 1024:
            raise ValueError('Finite 0.25..24 h, 1..4 captures and 32..1024 MiB threshold required')
        source, output = args.input_dir.absolute(), args.output_dir.absolute()
        if reparse(base.stat(follow_symlinks=False)) or source.parent != base or output.parent != base:
            raise ValueError('Direct workspace private report directories required')
        if reparse(source.stat(follow_symlinks=False)):
            raise ValueError('Source directory must not be a reparse point')
        source_status = source / 'status.json'
        if reparse(source_status.stat(follow_symlinks=False)) or source_status.stat().st_size > SAMPLE_LIMIT:
            raise ValueError('Bounded regular source status required')
        contract = json.loads(source_status.read_bytes(), object_pairs_hook=strict_object)
        source_hash = hashlib.sha256((workspace / 'scripts/pilot/host_storage_watch.py').read_bytes()).hexdigest()
        if (contract.get('administrator') is not True or contract.get('state') != 'running'
                or contract.get('sourceSha256') != source_hash):
            raise ValueError('Running reviewed elevated host observer required')
        end = min(datetime.now(timezone.utc) + timedelta(hours=args.hours), utc(contract['dueUtc']))
        duration = (end - datetime.now(timezone.utc)).total_seconds()
        if duration < 270:
            raise ValueError('Insufficient remaining observation window')
        output.mkdir(exist_ok=False)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    deadline = time.monotonic() + duration
    status = {'state': 'running', 'pid': os.getpid(), 'administrator': True,
              'startedUtc': datetime.now(timezone.utc).isoformat(), 'dueUtc': end.isoformat(),
              'sourceDirectory': str(source), 'sourceSha256': source_hash,
              'pollSeconds': 15, 'sourceIntervalSeconds': contract['intervalSeconds'],
              'dropThresholdBytes': args.drop_mib * MIB, 'capturesLimit': args.max_captures,
              'captures': [], 'traceBytes': 0, 'metadataLimitBytes': METADATA_LIMIT,
              'traceAccountingLimitBytes': TRACE_ACCOUNTING_LIMIT,
              'traceAccountingIsHardFileSizeLimit': False, 'postTriggerOnly': True,
              'cleanupPerformed': False, 'autostartConfigured': False, 'deviceCommandsSent': False}
    trigger = Trigger(args.drop_mib * MIB)
    cooldown_until = 0.0
    pending: list[str] = []
    path = output / 'status.json'
    try:
        while time.monotonic() < deadline - 270:
            current = observation(read_latest(source / 'samples.jsonl'), datetime.now(timezone.utc))
            pending = sorted(set(pending + trigger.inspect(current)))
            status.update(lastSampleUtc=current.at.isoformat(), freeDiskBytes=current.free)
            if pending and time.monotonic() >= cooldown_until:
                seconds = min(600, int(deadline - time.monotonic()) - 240)
                reasons, pending = pending, []
                trigger.rearm(current)
                capture = run_capture(workspace, seconds)
                capture['triggerReasons'] = reasons
                capture['triggerSampleUtc'] = current.at.isoformat()
                status['captures'].append(capture)
                status['traceBytes'] += capture.get('traceBytes', 0)
                cooldown_until = time.monotonic() + 600
                if capture['state'].startswith('unknown'):
                    status['state'] = 'stopped_unknown_capture'
                    break
                if status['traceBytes'] >= TRACE_ACCOUNTING_LIMIT:
                    status['state'] = 'stopped_trace_budget'
                    break
                if len(status['captures']) >= args.max_captures:
                    status['state'] = 'complete_capture_limit'
                    break
            if len(json.dumps(status).encode()) > METADATA_LIMIT // 2:
                status['state'] = 'stopped_metadata_budget'
                break
            write_json(path, status)
            time.sleep(min(15, max(0, deadline - 270 - time.monotonic())))
        else:
            status['state'] = 'complete_deadline'
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        status.update(state='stopped_error', errorType=type(error).__name__)
    except KeyboardInterrupt:
        status['state'] = 'interrupted'
    finally:
        status['finishedUtc'] = datetime.now(timezone.utc).isoformat()
        write_json(path, status)
    print(json.dumps(status))
    return 0 if status['state'].startswith('complete') else 2


if __name__ == '__main__':
    raise SystemExit(main())
