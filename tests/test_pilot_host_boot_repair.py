"""Actual PowerShell rejection/readiness paths; never request a disk repair."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell required')
SOURCE = Path(__file__).resolve().parents[1] / 'scripts/pilot/prepare_host_boot_repair.ps1'
POWERSHELL = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe')


@pytest.fixture
def local_copy(tmp_path):
    workspace = tmp_path / 'workspace'
    scripts = workspace / 'scripts' / 'pilot'
    scripts.mkdir(parents=True)
    source = scripts / SOURCE.name
    source.write_bytes(SOURCE.read_bytes())
    backup = workspace / '.local-pilot' / 'recovery'
    backup.mkdir(parents=True)
    (backup / 'source.zip').write_bytes(b'readiness-fixture; not a real backup')
    manifest = {
        'gitFsckPassed': True, 'remoteSourceMatches': True,
        'sourceRevision': 'fixture', 'independentBackupAvailable': False,
        'backupOnAffectedPhysicalDisk': True, 'notBackedUp': ['personal-files'],
        'files': [{'file': 'source.zip', 'bytes': (backup / 'source.zip').stat().st_size,
                   'sha256': hashlib.sha256((backup / 'source.zip').read_bytes()).hexdigest()}],
    }
    return source, backup, manifest


def invoke(source, backup):
    return subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-File', str(source),
         '-BackupDirectory', str(backup)], capture_output=True, timeout=10,
    )


def save(backup, manifest):
    (backup / 'backup-manifest.private.json').write_text(json.dumps(manifest), encoding='utf-8')


def test_default_verifies_only_without_scheduling_or_volume_queries(local_copy):
    source, backup, manifest = local_copy
    save(backup, manifest)
    result = invoke(source, backup)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report['state'] == 'local-copy-verified'
    assert not report['schedulingRequested']
    assert not report['restartPerformed']
    assert not report['repairCompleted']
    assert not report['independentBackupAvailable']
    assert not (backup / 'boot-repair-request.private.json').exists()


@pytest.mark.parametrize('defect', ['content', 'size', 'outside', 'unchecked_git'])
def test_invalid_recovery_copy_fails_before_any_scheduling(local_copy, defect):
    source, backup, manifest = local_copy
    if defect == 'content':
        (backup / 'source.zip').write_bytes(b'x' * manifest['files'][0]['bytes'])
    elif defect == 'size':
        manifest['files'][0]['bytes'] += 1
    elif defect == 'outside':
        manifest['files'][0]['file'] = '../../outside.zip'
    else:
        manifest['gitFsckPassed'] = False
    save(backup, manifest)
    assert invoke(source, backup).returncode != 0
    assert not (backup / 'boot-repair-request.private.json').exists()


def test_output_outside_workspace_rejected_before_any_read(local_copy, tmp_path):
    source, _, _ = local_copy
    assert invoke(source, tmp_path / 'elsewhere').returncode != 0


def test_collector_cannot_write_through_directory_junction(tmp_path):
    workspace = tmp_path / 'workspace'
    scripts = workspace / 'scripts' / 'pilot'
    scripts.mkdir(parents=True)
    source = scripts / 'collect_host_repair.ps1'
    source.write_bytes(SOURCE.with_name(source.name).read_bytes())
    reports = workspace / '.local-pilot'
    reports.mkdir()
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    # Native DirectoryInfo creation needs no shell-built deletion or path commands.
    junction = reports / 'junction'
    setup = subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-Command',
         'New-Item -ItemType Junction -Path $env:REPAIR_TEST_JUNCTION -Target $env:REPAIR_TEST_TARGET | Out-Null'],
        env=os.environ | {'REPAIR_TEST_JUNCTION': str(junction), 'REPAIR_TEST_TARGET': str(elsewhere)},
        capture_output=True, timeout=10,
    )
    if setup.returncode:
        pytest.skip('Junction creation unavailable on test host')
    result = subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-File', str(source),
         '-OutputDirectory', str(junction)], capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert list(elsewhere.iterdir()) == []
