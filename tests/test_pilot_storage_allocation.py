"""Execute rejection paths without issuing privileged volume queries."""
import ctypes
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows PowerShell collector')
SOURCE = Path(__file__).parents[1] / 'scripts/pilot/collect_storage_allocation.ps1'


@pytest.fixture
def collector(tmp_path):
    source = tmp_path / 'scripts/pilot/collect_storage_allocation.ps1'
    source.parent.mkdir(parents=True)
    source.write_bytes(SOURCE.read_bytes())
    reports = tmp_path / '.local-pilot'
    reports.mkdir()
    return source, reports


def invoke(source, arguments):
    return subprocess.run(
        ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(source), *arguments],
        capture_output=True, timeout=10,
    )


@pytest.mark.parametrize('arguments', [
    ['-Samples', '0'], ['-Samples', '62'],
    ['-Samples', '61', '-IntervalSeconds', '120'],
])
def test_invalid_or_overlong_window_never_creates_reports(collector, arguments):
    source, reports = collector
    assert invoke(source, arguments).returncode == 1
    assert list(reports.iterdir()) == []


def test_non_admin_stops_before_volume_queries_or_directory_creation(collector):
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.skip('No actual volume reads from a unit test running as administrator')
    source, reports = collector
    result = invoke(source, ['-Samples', '1'])
    assert result.returncode == 2
    assert b'Administrator required' in result.stderr
    assert result.stdout == b''
    assert list(reports.iterdir()) == []
