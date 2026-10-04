import json
import os
import platform
import stat
import sys
from types import SimpleNamespace

import pytest

from scripts.pilot import disk_growth as watch


@pytest.mark.parametrize(('original', 'native'), [
    (r'C:\scope\file.bin', r'\\?\C:\scope\file.bin'),
    (r'\\server\share\file.bin', r'\\?\UNC\server\share\file.bin'),
    (r'\\?\C:\scope\file.bin', r'\\?\C:\scope\file.bin'),
])
def test_windows_extended_paths_preserve_local_and_unc_identity(monkeypatch, original, native):
    monkeypatch.setattr(watch.platform, 'system', lambda: 'Windows')
    assert watch.native_path(original) == native
    assert str(watch.display_path(native)) == original.removeprefix('\\\\?\\')


@pytest.mark.skipif(platform.system() != 'Windows', reason='Windows long-path filesystem regression')
def test_scan_and_allocation_include_files_beyond_windows_legacy_path_limit(tmp_path):
    directories = []
    directory = tmp_path
    file = None
    try:
        for number in range(5):
            directory = directory / (str(number) + 'x' * 50)
            os.mkdir(watch.native_path(directory))
            directories.append(directory)
        file = directory / 'payload.bin'
        assert len(str(file)) > 260
        with open(watch.native_path(file), 'wb') as handle:
            handle.write(b'long path payload')
        report, _ = watch.scan_root(tmp_path, excluded=tmp_path / 'out')
        assert report['state'] == 'complete' and report['errors'] == 0
        assert report['logicalBytesSeen'] == 17 and report['filesSeen'] == 1
        measured = watch.file_state(file)
        assert measured['state'] == 'measured' and measured['logicalBytes'] == 17
        assert measured['allocatedBytes'] is not None and measured['allocationError'] is None
    finally:
        if file is not None:
            assert tmp_path in file.parents
            if os.path.exists(watch.native_path(file)):
                os.unlink(watch.native_path(file))
        for directory in reversed(directories):
            assert tmp_path in directory.parents
            os.rmdir(watch.native_path(directory))


def test_access_errors_have_bounded_path_evidence_and_remain_partial(tmp_path, monkeypatch):
    denied = tmp_path / 'locked'
    denied.mkdir()
    original = watch.os.scandir
    def fail_locked(path):
        if str(watch.display_path(path)) == str(denied):
            raise PermissionError('denied')
        return original(path)
    monkeypatch.setattr(watch.os, 'scandir', fail_locked)
    report, _ = watch.scan_root(tmp_path, excluded=tmp_path / 'out')
    assert report['state'] == 'partial_access'
    assert report['errorSamples'] == [{'path': 'locked', 'type': 'PermissionError'}]


def test_sparse_growth_with_unchanged_logical_length_is_detected():
    old = {'image': {'state': 'measured', 'logicalBytes': 6 * 1024 ** 3,
                     'allocatedBytes': 1024 ** 2, 'identity': [1, 2]}}
    new = {'image': dict(old['image'], allocatedBytes=5 * 1024 ** 3)}
    change = watch.changed_files(old, new)[0]
    assert change['logicalDeltaBytes'] == 0
    assert change['allocatedDeltaBytes'] == 5 * 1024 ** 3 - 1024 ** 2


def test_missing_allocation_and_access_failure_cannot_become_zero():
    old = {'file': {'state': 'measured', 'logicalBytes': 200, 'allocatedBytes': None}}
    new = {'file': {'state': 'measured', 'logicalBytes': 300, 'allocatedBytes': None}}
    assert watch.changed_files(old, new)[0]['allocatedDeltaBytes'] is None
    assert watch.changed_files(old, {'file': {'state': 'unavailable'}}) == []


def test_replacement_is_separate_from_same_file_growth():
    old = {'file': {'logicalBytes': 100, 'identity': [1, 2]}}
    new = {'file': {'logicalBytes': 100, 'identity': [1, 3]}}
    assert watch.changed_files(old, new)[0]['event'] == 'replaced'


def test_candidate_membership_does_not_claim_file_creation_or_deletion():
    changes = watch.changed_files({'older': {'logicalBytes': 2}}, {'larger': {'logicalBytes': 3}})
    assert {item['event'] for item in changes} == {'new_to_candidate_set', 'left_candidate_set'}
    assert all(item['logicalDeltaBytes'] is None for item in changes)


def test_complete_scan_totals_skip_watcher_output_and_bound_candidates(tmp_path):
    root = tmp_path / 'root'
    output = root / 'watcher'
    output.mkdir(parents=True)
    (output / 'sample.json').write_bytes(b'x' * 40)
    (root / 'a.bin').write_bytes(b'x' * watch.MIB)
    (root / 'b.bin').write_bytes(b'x' * (watch.MIB + 1))
    report, candidates = watch.scan_root(root, excluded=output, candidate_limit=1)
    assert report['state'] == 'complete' and report['logicalBytesSeen'] == watch.MIB * 2 + 1
    assert report['filesSeen'] == 2 and list(candidates) == ['b.bin']


def test_incomplete_scan_is_never_used_for_growth_subtraction(tmp_path):
    (tmp_path / 'file').write_bytes(b'x')
    partial, _ = watch.scan_root(tmp_path, excluded=tmp_path / 'none', max_entries=0)
    assert partial['state'] == 'partial_budget'
    complete = {'state': 'complete', 'logicalBytesSeen': 5, 'directoryTotals': {'.': 5}}
    assert watch.changed_roots({'root': complete}, {'root': partial}) == []
    assert watch.changed_roots({'root': partial}, {'root': complete}) == []


def test_missing_root_reports_unavailable_not_empty(tmp_path):
    report, candidates = watch.scan_root(tmp_path / 'missing', excluded=tmp_path / 'out')
    assert report['state'] == 'unavailable' and 'logicalBytesSeen' not in report
    assert candidates == {}


def test_junction_attribute_is_recognized_without_following_target():
    info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
    assert watch.reparse(info)


def test_report_limits_prevent_oversize_or_total_quota_overrun(tmp_path):
    with pytest.raises(ValueError, match='storage_budget'):
        watch.save_sample(tmp_path, 0, {'data': 'x' * watch.MAX_SAMPLE_BYTES}, used=0, limit=2 * watch.MIB)
    with pytest.raises(ValueError, match='storage_budget'):
        watch.save_sample(tmp_path, 1, {'data': 'small'}, used=99, limit=100)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('extra', [
    ['--samples', '0'], ['--samples', '98'], ['--interval', '1'],
    ['--samples', '97', '--interval', '3600'], ['--max-total-mib', '100'],
    ['--roots-every', '0'],
])
def test_invalid_unbounded_settings_rejected_before_any_output(tmp_path, monkeypatch, extra):
    output = tmp_path / 'out'
    monkeypatch.setattr(sys, 'argv', ['watch', '--root', str(tmp_path), '--output-dir', str(output), *extra])
    with pytest.raises(SystemExit) as error:
        watch.main()
    assert error.value.code == 2 and not output.exists()


def test_one_shot_exits_and_reports_existing_file_without_reading_its_contents(tmp_path, monkeypatch):
    file = tmp_path / 'image'
    file.write_bytes(b'private contents')
    output = tmp_path / 'out'
    monkeypatch.setattr(sys, 'argv', ['watch', '--file', str(file), '--samples', '1', '--output-dir', str(output)])
    assert watch.main() == 0
    sample = json.loads((output / 'sample-000.json').read_text())
    status = json.loads((output / 'status.json').read_text())
    assert sample['watchedFiles'][str(file)]['logicalBytes'] == 16
    assert status['state'] == 'complete' and status['samplesWritten'] == 1
    assert 'private contents' not in (output / 'sample-000.json').read_text()


def test_existing_output_cannot_be_overwritten(tmp_path, monkeypatch):
    output = tmp_path / 'out'
    output.mkdir()
    sentinel = output / 'sentinel'
    sentinel.write_text('preserved')
    monkeypatch.setattr(sys, 'argv', ['watch', '--root', str(tmp_path), '--samples', '1', '--output-dir', str(output)])
    with pytest.raises(FileExistsError):
        watch.main()
    assert sentinel.read_text() == 'preserved'


def test_overlapping_roots_rejected_before_scanning(tmp_path, monkeypatch):
    output = tmp_path / 'out'
    monkeypatch.setattr(sys, 'argv', ['watch', '--root', str(tmp_path), '--root', str(tmp_path / 'sub'), '--output-dir', str(output)])
    with pytest.raises(SystemExit) as error:
        watch.main()
    assert error.value.code == 2 and not output.exists()


def test_low_disk_stops_before_any_scan_or_sample(tmp_path, monkeypatch):
    output = tmp_path / 'out'
    monkeypatch.setattr(sys, 'argv', ['watch', '--root', str(tmp_path), '--samples', '1', '--output-dir', str(output)])
    monkeypatch.setattr(watch.shutil, 'disk_usage', lambda _: SimpleNamespace(free=128 * watch.MIB))
    monkeypatch.setattr(watch, 'scan_root', lambda *a, **kw: pytest.fail('low disk must stop before scanning'))
    assert watch.main() == 2
    status = json.loads((output / 'status.json').read_text())
    assert status['state'] == 'stopped_low_disk' and status['samplesWritten'] == 0
    assert not list(output.glob('sample-*.json'))


def test_storage_budget_failure_is_recorded_and_exits_without_retries(tmp_path, monkeypatch):
    output = tmp_path / 'out'
    file = tmp_path / 'file'
    file.write_bytes(b'x')
    monkeypatch.setattr(sys, 'argv', ['watch', '--file', str(file), '--samples', '1', '--output-dir', str(output)])
    def over_budget(*args, **kwargs):
        raise ValueError('report_storage_budget_exceeded')
    monkeypatch.setattr(watch, 'save_sample', over_budget)
    assert watch.main() == 2
    status = json.loads((output / 'status.json').read_text())
    assert status['state'] == 'stopped_error' and status['samplesWritten'] == 0


def test_free_delta_compares_matching_end_of_scan_measurements(tmp_path, monkeypatch):
    output = tmp_path / 'out'
    file = tmp_path / 'file'
    file.write_bytes(b'x')
    monkeypatch.setattr(sys, 'argv', ['watch', '--file', str(file), '--samples', '2', '--interval', '60', '--output-dir', str(output)])
    free_values = iter([1000, 900, 800, 700])
    monkeypatch.setattr(watch.shutil, 'disk_usage', lambda _: SimpleNamespace(free=next(free_values) * watch.MIB))
    monkeypatch.setattr(watch.time, 'sleep', lambda _: None)
    assert watch.main() == 0
    last = json.loads((output / 'sample-001.json').read_text())
    assert last['freeDiskBytes'] == 700 * watch.MIB
    assert last['freeDeltaFromPreviousSample'] == -200 * watch.MIB
