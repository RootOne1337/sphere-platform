import math

import pytest

from scripts.pilot.world_map_lab.pedestrian_gaze import face_travel


def test_turn_in_place_for_a_side_street_or_a_reversal():
    for degrees in [45, 90, -90, 179]:
        intent = face_travel(math.radians(degrees), 0, 0.2)
        assert intent.forward == 0 and intent.right == 0
        assert abs(intent.turn) <= math.radians(11) + 1e-12
        assert intent.turn * degrees > 0


def test_walk_forward_through_wraparound_and_slow_for_turn():
    straight = face_travel(math.radians(-179), math.radians(179), 0.1)
    assert straight.forward == pytest.approx(1, abs=0.001) and straight.turn == 0
    turning = face_travel(math.radians(25), 0, 0.1)
    assert 0 < turning.forward < 0.6 and turning.right < 0 and turning.turn > 0

    assert abs(math.degrees(math.atan2(turning.right, turning.forward))) <= 8.001
