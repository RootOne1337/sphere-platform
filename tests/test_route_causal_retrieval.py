from types import SimpleNamespace

import numpy as np

from scripts.pilot.route_causal_retrieval import CausalReferenceLocalizer


def shortlist(*, start_mode="recognized_route", has_localized=False, age=None):
    previous = None if age is None else (None, None, 3.2, 10 - age)
    tracker = SimpleNamespace(
        np=np, previous=previous, confirmations=3 if previous else 0, last_received=10,
        reference_times=np.arange(8) * .25, cumulative=np.arange(8),
        start_mode=start_mode, _has_localized=has_localized,
    )
    scores = np.array([10, 9, 8, 7, 6, 0, 1, 2])
    return CausalReferenceLocalizer._shortlist(tracker, scores)


def test_recent_pose_reserves_two_local_checks_and_keeps_best_global():
    assert shortlist(age=.15) == ([5, 4, 3], "recent_pose")


def test_explicit_start_reserves_one_check_only_before_first_localization():
    assert shortlist(start_mode="beginning") == ([5, 6, 1], "explicit_start")
    assert shortlist(start_mode="beginning", has_localized=True, age=.51) == ([5, 6, 7], "global")
    assert shortlist() == ([5, 6, 7], "global")
