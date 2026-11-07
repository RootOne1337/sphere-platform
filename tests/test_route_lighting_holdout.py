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


def test_continuous_source_window_skips_map_keyframes_and_preserves_source_clock():
    assert replay.source_window("0:6.6") == (0, 594000)
    with pytest.raises(argparse.ArgumentTypeError):
        replay.source_window("0:8.0001")
    frame = SimpleNamespace(to_ndarray=lambda **_: np.zeros((4, 8, 3), dtype=np.uint8))
    frames = (({"index": i, "relative_ticks_90k": i * 9000}, frame) for i in range(7))
    batch, = replay.sample_holdout_windows(frames, [(0, 54000)], excluded={0, 3})
    assert [(index, time) for index, time, _ in batch] == [(1, .1), (4, .4)]


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


def test_sequence_vote_keeps_global_escape_and_rechecks_current_evidence():
    from scripts.pilot.check_route_coarse_retrieval import sequence_vote_candidates, vote_candidates

    votes = np.array([0, 31, 29, 0, 0, 0, 25, 0, 0, 11, 20])
    previous = np.zeros_like(votes)
    previous[2] = previous[9] = 1
    neighborhoods = np.eye(len(votes), dtype=bool)

    assert vote_candidates(votes) == [1, 6, 10]
    assert sequence_vote_candidates(votes, None, neighborhoods) == [1, 6, 10]
    assert sequence_vote_candidates(votes, previous, neighborhoods) == [1, 2, 6]
    assert sequence_vote_candidates(np.zeros_like(votes), previous, neighborhoods) == []
    assert votes[1] == 31


def test_neighborhood_vote_keeps_two_global_candidates_and_uses_current_support():
    from scripts.pilot.check_route_coarse_retrieval import neighborhood_vote_candidates

    votes = np.array([31, 24, 24, 0, 0, 0, 25, 0, 11, 0, 20])
    assert neighborhood_vote_candidates(votes) == [0, 6, 1]
    votes[1:3] = 11
    assert neighborhood_vote_candidates(votes) == [0, 6, 10]
    assert neighborhood_vote_candidates(np.zeros(2)) == []
