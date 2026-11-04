import argparse
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import check_route_lighting_replay as replay


@pytest.mark.parametrize("value", ["0:2.4001", "nan:2", "0:inf", "2:1", "0:1:2"])
def test_holdout_window_refuses_invalid_or_unbounded_times(value):
    with pytest.raises(argparse.ArgumentTypeError):
        replay.holdout_window(value)


def test_holdout_rejects_overlaps_and_windows_past_the_capture():
    first = replay.holdout_window("0:2.4")
    second = replay.holdout_window("2.4:4.8")
    assert replay.validate_holdout_windows([second, first], second[1]) == [first, second]
    with pytest.raises(ValueError, match="holdout_window_scope"):
        replay.validate_holdout_windows([first, first], second[1])
    with pytest.raises(ValueError, match="holdout_window_scope"):
        replay.validate_holdout_windows([first, second], second[1] - 1)
    with pytest.raises(ValueError, match="holdout_window_scope"):
        replay.validate_holdout_windows([(tick, tick + 1) for tick in range(7)], 10)


def test_holdout_keeps_original_timestamps_and_does_not_cross_window_boundaries():
    ticks = [0, 10000, 18000, 81000, 90000, 99000, 108000, 180000]
    frame = SimpleNamespace(to_ndarray=lambda **_: np.zeros((4, 8, 3), dtype=np.uint8))
    frames = (({"index": index, "relative_ticks_90k": tick}, frame)
              for index, tick in enumerate(ticks))
    result = replay.sample_holdout_windows(frames, [(0, 90000), (90000, 180000)])
    assert [[(index, time) for index, time, _ in batch] for batch in result] == [
        [(0, 0.), (2, .2), (3, .9)], [(4, 1.), (6, 1.2)]]


def test_holdout_rejects_reuploaded_source_video(tmp_path):
    source, uploaded = tmp_path / "source", tmp_path / "upload"
    hashes = {str(source / "video.h264"): "a", str(uploaded / "video.h264"): "a",
              str(source / "manifest.json"): "b", str(uploaded / "manifest.json"): "c"}
    with pytest.raises(ValueError, match="holdout_same_source_video"):
        replay.independent_capture(source, uploaded, hashes)


def test_window_coverage_counts_delayed_poses_and_silent_windows_as_unavailable():
    windows = [(0, 180000), (180000, 360000)]
    runs = [
        {"rows": [{"mediaSeconds": 0.4, "localizedOnTime": True},
                  {"mediaSeconds": 1.4, "localizedOnTime": False}], "dropped": 1},
        {"rows": [{"mediaSeconds": 2.3, "localizedOnTime": False}], "dropped": 0},
    ]
    start, silent = replay.holdout_coverage(windows, runs)
    assert start["localizedOnTime"] == 1
    assert start["scheduled"] == 3
    assert start["firstLocalizedAfterSeconds"] == 0.4
    assert start["longestWithoutLocalizedFrameSeconds"] == 1.6
    assert silent["firstLocalizedAfterSeconds"] is None
    assert silent["longestWithoutLocalizedFrameSeconds"] == 2.0


def test_coarse_replay_reports_outage_and_compares_scheduled_jpegs_after_drops():
    from scripts.pilot.check_route_coarse_retrieval import paced_holdout_coverage

    windows = [(0, 90000)]
    schedule = [{"frame": 10, "seconds": 0.2, "jpegSha256": "a" * 64},
                {"frame": 20, "seconds": 0.6, "jpegSha256": "b" * 64}]
    baseline = {"scheduledQueries": schedule, "dropped": 0, "rows": [
        {"seconds": 0.2, "localizedOnTime": False, "ageMs": 40, "diagnostic": {}, "reason": "unknown"},
        {"seconds": 0.6, "localizedOnTime": False, "ageMs": 40, "diagnostic": {}, "reason": "unknown"}]}
    vote = {"scheduledQueries": schedule, "dropped": 1, "rows": [
        {"seconds": 0.2, "localizedOnTime": False, "ageMs": 260,
         "diagnostic": {"verifiedCandidateCount": 1}, "reason": "expired"}]}
    result = paced_holdout_coverage(windows, {"baseline": [baseline], "vote": [vote]})
    coverage = result["vote"][0]
    assert coverage["scheduled"] == 2
    assert coverage["dropped"] == coverage["repliesOver250Ms"] == 1
    assert coverage["localizedOnTime"] == coverage["framesWithVerifiedGeometryOnTime"] == 0
    assert coverage["longestWithoutLocalizedFrameSeconds"] == 1
    assert coverage["reasons"] == {"expired": 1}

    vote["scheduledQueries"] = [schedule[0], {**schedule[1], "jpegSha256": "c" * 64}]
    with pytest.raises(ValueError, match="route_coarse_replay_query_mismatch"):
        paced_holdout_coverage(windows, {"baseline": [baseline], "vote": [vote]})
