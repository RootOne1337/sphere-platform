"""Reject ambiguous attribution, oversized reports, and unsafe launch windows."""
import json
import platform
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.pilot import host_storage_watch as watch


@pytest.mark.parametrize('values', [(1, 120, 8, 16), (722, 120, 8, 16),
    (241, 59, 8, 16), (241, 601, 8, 16), (721, 600, 8, 16),
    (241, 120, 0, 16), (241, 120, 61, 16), (241, 120, 8, 33)])
def test_invalid_or_unbounded_windows_are_rejected(values):
    with pytest.raises(ValueError):
        watch.validate_window(*values)


def test_eight_hour_window_and_boundary_day_are_valid():
    watch.validate_window(241, 120, 8, 16)
    watch.validate_window(145, 600, 60, 32)


def test_sample_and_total_budget_are_enforced_before_write():
    with pytest.raises(ValueError):
        watch.encode_sample({'large': 'a' * watch.SAMPLE_LIMIT}, 0, 16 * watch.MIB)
    with pytest.raises(ValueError):
        watch.encode_sample({'index': 2}, watch.MIB - watch.STATUS_ALLOWANCE, watch.MIB)
    assert json.loads(watch.encode_sample({'index': 2}, 0, watch.MIB)) == {'index': 2}


def sample(*, boot='epoch1', vss='measured', allocated=100):
    rows = [{'volume': 'C', 'diffVolume': 'C', 'allocatedBytes': allocated, 'usedBytes': 90}]
    return {'freeDiskBytes': 500, 'files': {}, 'host': {'state': 'measured',
        'value': {'bootUtc': boot, 'committedBytes': 1000,
                  'vss': {'state': vss, 'rows': rows if vss == 'measured' else []}}}}


def test_same_boot_exact_vss_delta_does_not_claim_writer_identity():
    before, after = sample(), sample(allocated=300)
    after['freeDiskBytes'] = 300
    delta = watch.trend(before, after)
    assert delta['freeDiskDeltaBytes'] == -200
    assert delta['vssDeltas'][0]['allocatedDeltaBytes'] == 200
    assert delta['writerAttribution'] == 'UNDETERMINED'


def test_missing_vss_or_boot_change_is_not_zero_growth():
    assert 'vssDeltas' not in watch.trend(sample(), sample(vss='unavailable'))
    assert 'committedBytesDelta' not in watch.trend(sample(), sample(boot='epoch2'))
    assert 'committedBytesDelta' not in watch.trend(sample(boot=None), sample(boot=None))


def test_vss_membership_change_is_explicit_and_not_invented_negative_growth():
    after = sample()
    after['host']['value']['vss']['rows'] = []
    delta = watch.trend(sample(), after)
    assert delta['vssDeltas'] == [] and delta['vssMembershipChanged'] is True


def test_failed_native_read_never_persists_stderr_or_substitutes_zero(monkeypatch):
    monkeypatch.setattr(watch.subprocess, 'run', lambda *a, **kw:
        SimpleNamespace(returncode=1, stdout=b'', stderr=b'private command credentials'))
    result = watch.json_probe(['fixed-metadata-command'])
    assert result == {'state': 'unavailable', 'exitCode': 1, 'errorType': 'native_error'}


def test_large_or_invalid_native_output_remains_unknown(monkeypatch):
    monkeypatch.setattr(watch.subprocess, 'run', lambda *a, **kw:
        SimpleNamespace(returncode=0, stdout=b'x' * (watch.SAMPLE_LIMIT + 1)))
    assert watch.json_probe(['fixed-command'])['errorType'] == 'output_budget'
    monkeypatch.setattr(watch.subprocess, 'run', lambda *a, **kw:
        SimpleNamespace(returncode=0, stdout=b'bad json'))
    assert watch.json_probe(['fixed-command'])['state'] == 'unavailable'


@pytest.mark.skipif(platform.system() != 'Windows', reason='Windows native collector launch')
def test_invalid_cli_creates_no_report_even_on_elevated_host():
    root = Path(__file__).resolve().parents[1]
    target = root / '.local-pilot' / 'host-storage-invalid-test'
    assert not target.exists()
    result = subprocess.run([str(root / '.venv-audit/Scripts/python.exe'), '-m',
        'scripts.pilot.host_storage_watch', '--output-dir', str(target), '--samples', '1'],
        capture_output=True, timeout=15, cwd=root)
    assert result.returncode != 0 and not target.exists()
