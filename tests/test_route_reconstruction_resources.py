import copy

import pytest

from scripts.pilot.resource_guard import evaluate
from scripts.pilot.route_reconstruction_resources import GIB, findings, profile


def snapshot(**changes):
    value = dict(system='Windows', freeDiskBytes=40 * GIB,
                 availableRamBytes=10 * GIB, totalRamBytes=48 * GIB,
                 committedBytes=86 * GIB, commitLimitBytes=100 * GIB,
                 volumeHealthStatus='Healthy', volumeOperationalStatus=['OK'])
    value.update(changes)
    return value


def source(tmp_path, size):
    (tmp_path / 'input').mkdir()
    # File metadata is the input; a sparse file avoids allocating a large clip.
    with (tmp_path / 'input/video.h264').open('wb') as output:
        output.truncate(size)
    return tmp_path


def test_small_actual_clip_reserves_six_gib_and_leaves_host_four(tmp_path):
    value = profile(source(tmp_path, 40825272), route_only=True)
    assert value['sourceVideoBytes'] == 40825272
    assert value['minRamGiB'] == 6 and value['hostReserveGiB'] == 4
    assert value['taskReserveGiB'] == 2 and value['maxCommitPercent'] == 90
    assert value['minDiskGiB'] == 20 and not value['modelLoaded']


def test_two_gib_source_uses_eleven_and_half_gib(tmp_path):
    value = profile(source(tmp_path, 2 * GIB), route_only=True)
    assert value['minRamGiB'] == 11.5
    assert value['taskReserveGiB'] == 7.5


def test_video_budget_rounds_up_to_quarter_gib(tmp_path):
    value = profile(source(tmp_path, GIB // 4 + 1), route_only=True)
    assert value['minRamGiB'] == 6.5


@pytest.mark.parametrize('size', [0, 2 * GIB + 1])
def test_invalid_size_keeps_conservative_post_upload_budget(tmp_path, size):
    value = profile(source(tmp_path, size), route_only=True)
    assert value['sourceVideoBytes'] is None and not value['sourceSizeKnown']
    assert value['minRamGiB'] == 12


def test_unknown_post_upload_size_is_twelve_but_explicit_upload_is_six(tmp_path):
    assert profile(tmp_path, route_only=True)['minRamGiB'] == 12
    value = profile(tmp_path, route_only=True, uploading=True)
    assert value['minRamGiB'] == 6 and value['uploading']
    assert value['sourceVideoBytes'] is None


def test_directory_is_not_a_source_video(tmp_path):
    (tmp_path / 'input/video.h264').mkdir(parents=True)
    assert profile(tmp_path, route_only=True)['minRamGiB'] == 12


def test_symlink_size_is_unknown_even_if_target_is_regular(tmp_path, monkeypatch):
    job = source(tmp_path, 100)
    from pathlib import Path
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink',
                        lambda path:path.name == 'video.h264' or original(path))
    assert profile(job, route_only=True)['minRamGiB'] == 12


def test_symlink_input_directory_is_unknown(tmp_path, monkeypatch):
    job = source(tmp_path, 100)
    from pathlib import Path
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink',
                        lambda path:path.name == 'input' or original(path))
    assert profile(job, route_only=True)['minRamGiB'] == 12


def test_heavy_job_keeps_default_evaluator_and_eighty_five_percent(tmp_path):
    assert profile(tmp_path, route_only=False) is None
    state = snapshot()
    assert 'commit_headroom_low' in evaluate(state)
    assert findings(state, None) == evaluate(state)
    calls = []
    expected = ['custom-default']

    def evaluator(value, **kwargs):
        calls.append((value, kwargs))
        return expected

    assert findings(state, None, evaluator) is expected
    assert calls == [(state, {})]


def test_cpu_route_can_admit_eighty_six_percent_with_sufficient_absolute_reserve(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    state = snapshot()
    assert findings(state, budget) == []
    assert 'commit_headroom_low' in evaluate(state)


def test_abundant_ram_does_not_waive_commit_pressure(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    assert 'commit_headroom_low' in findings(snapshot(availableRamBytes=30 * GIB,
                                                    committedBytes=90 * GIB), budget)


def test_commit_headroom_does_not_waive_ram_pressure(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    result = findings(snapshot(availableRamBytes=5 * GIB, committedBytes=20 * GIB), budget)
    assert result == ['ram_headroom_low']


def test_absolute_reserve_rejects_even_below_ninety_percent(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    state = snapshot(committedBytes=44 * GIB, commitLimitBytes=49 * GIB)
    assert 44 / 49 < .9
    assert findings(state, budget) == ['commit_headroom_low']


def test_exact_absolute_reserve_is_inclusive_but_percentage_ceiling_is_not(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    assert findings(snapshot(committedBytes=44 * GIB, commitLimitBytes=50 * GIB), budget) == []
    assert 'commit_headroom_low' in findings(snapshot(committedBytes=90 * GIB), budget)


@pytest.mark.parametrize('changes', [dict(committedBytes=None), dict(commitLimitBytes=None),
                                    dict(committedBytes=True), dict(commitLimitBytes=0),
                                    dict(committedBytes=101 * GIB)])
def test_unknown_or_invalid_commit_counters_refuse(tmp_path, changes):
    budget = profile(tmp_path, route_only=True, uploading=True)
    assert 'commit_measurement_unavailable' in findings(snapshot(**changes), budget)


def test_unknown_absolute_commit_is_not_hidden_by_injected_evaluator(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    state = snapshot(committedBytes=None)
    assert findings(state, budget, lambda *args, **kwargs:[]) == ['commit_measurement_unavailable']


def test_disk_and_volume_guards_remain_in_force(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    result = findings(snapshot(freeDiskBytes=19 * GIB, volumeHealthStatus='Warning'), budget)
    assert 'disk_headroom_low' in result and 'volume_not_ready' in result


def test_linux_keeps_underlying_memory_accounting_without_windows_commit(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    assert findings(dict(system='Linux', availableRamBytes=10 * GIB,
                         totalRamBytes=48 * GIB, freeDiskBytes=40 * GIB), budget) == []


def test_measurements_and_profile_are_not_mutated_and_explicit_limits_are_forwarded(tmp_path):
    budget = profile(tmp_path, route_only=True, uploading=True)
    state = snapshot()
    before = copy.deepcopy((state, budget))
    calls = []

    def evaluator(value, **kwargs):
        calls.append(kwargs)
        return []

    assert findings(state, budget, evaluator) == []
    assert calls == [dict(min_ram_gib=6., min_disk_gib=20., max_commit_percent=90)]
    assert (state, budget) == before


@pytest.mark.parametrize('changes', [dict(minRamGiB=4), dict(minRamGiB=13),
                                    dict(maxCommitPercent=99), dict(minDiskGiB=1),
                                    dict(hostReserveGiB=0), dict(taskReserveGiB=0),
                                    dict(taskReserveGiB=10 ** 500),
                                    dict(modelLoaded=True), dict(kind='dense')])
def test_profile_cannot_silently_relax_other_guards(tmp_path, changes):
    budget = profile(tmp_path, route_only=True, uploading=True)
    budget.update(changes)
    with pytest.raises(ValueError, match='route_reconstruction_resource_profile'):
        findings(snapshot(), budget)


@pytest.mark.parametrize('kwargs', [dict(route_only=1), dict(route_only=True, uploading=1)])
def test_scope_flags_require_explicit_booleans(tmp_path, kwargs):
    with pytest.raises(ValueError, match='route_reconstruction_resource_scope'):
        profile(tmp_path, **kwargs)
