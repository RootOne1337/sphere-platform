from types import SimpleNamespace

import pytest

from scripts.pilot import reconstruct_route as pipeline
from scripts.pilot import resource_guard


def test_fast_checks_refresh_native_counters_every_call_and_volume_within_three_seconds(tmp_path, monkeypatch):
    gib=2**30; clock=[10.]; counts={'full':0,'memory':0,'disk':0}
    monkeypatch.setattr(pipeline.time,'monotonic',lambda:clock[0])
    def memory():
        counts['memory']+=1
        return dict(availableRamBytes=12*gib,totalRamBytes=32*gib,committedBytes=10*gib,commitLimitBytes=40*gib)
    def disk(_):counts['disk']+=1;return SimpleNamespace(free=40*gib)
    def full(_):
        counts['full']+=1
        return dict(system='Windows',freeDiskBytes=disk(None).free,volumeHealthStatus='Healthy',
                    volumeOperationalStatus=['OK'],**memory())
    monkeypatch.setattr(resource_guard,'windows_memory',memory)
    monkeypatch.setattr(pipeline.shutil,'disk_usage',disk)
    monkeypatch.setattr(pipeline,'collect',full)
    check=pipeline.make_observation_checkpoint(tmp_path)
    for _ in range(100):check()
    assert counts=={'full':1,'memory':100,'disk':100}
    clock[0]+=3.;check()
    assert counts=={'full':2,'memory':101,'disk':101}
    (tmp_path/'CANCEL').touch()
    with pytest.raises(RuntimeError,match='cancelled'):check()
    assert counts['memory']==101


def test_missing_fresh_memory_fails_closed_without_reusing_cached_snapshot(tmp_path,monkeypatch):
    gib=2**30
    monkeypatch.setattr(pipeline,'collect',lambda _:dict(system='Windows',freeDiskBytes=40*gib,
        availableRamBytes=12*gib,totalRamBytes=32*gib,committedBytes=10*gib,commitLimitBytes=40*gib,
        volumeHealthStatus='Healthy',volumeOperationalStatus=['OK']))
    monkeypatch.setattr(pipeline.shutil,'disk_usage',lambda _:SimpleNamespace(free=40*gib))
    def failed():raise OSError('unavailable')
    monkeypatch.setattr(resource_guard,'windows_memory',failed)
    check=pipeline.make_observation_checkpoint(tmp_path);check()
    with pytest.raises(RuntimeError,match='resource_guard'):check()
    assert (tmp_path/'resource-refusal.json').is_file()
