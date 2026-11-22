from unittest.mock import Mock, patch

from scripts.pilot.world_map_lab.world_walk_trip import WalkTrip


def test_walk_trip_reacquires_and_requires_stable_arrival():
    road = Mock()
    road.levels.return_value = [0]
    surface = Mock()
    surface.sweep.return_value = (0, True)
    goal = [10, 0, 0]

    def pose(x, heading=0):
        return {"eye": [x, 0, 1.6], "heading": heading, "supports": 32}

    def plan_route(_, stops, mode, __, *, surface):
        assert all(type(value) in (int, float) for stop in stops for value in stop)
        assert (mode, surface) == ("walk", "crossings")
        return {"status": "complete", "legs": [{"path": [[0, 0, 0], [5, 0, 0], goal]}]}

    for _ in range(2):
        trip = WalkTrip(road, goal, surface)
        with patch("scripts.pilot.world_map_lab.world_walk_trip.plan", side_effect=plan_route):
            assert trip.decide(pose(0, 1), 1)["reason"] == "confirming_position"
            assert trip.decide(pose(0, 1), 1.2)["path"][-1] == goal
            aligned = trip.decide(pose(0, 1), 1.4)
            assert aligned["lookRadians"] == -1 and aligned["stick"] == [0, 0]
            assert trip.decide(None, 1.6)["stick"] == [0, 0]
            assert trip.decide(pose(0), 1.8)["reason"] == "confirming_position"
            assert trip.decide(pose(0), 2)["stick"][1] < 0
            assert trip.decide(pose(9.8), 2.2)["reason"] == "confirming_position"
            assert trip.decide(pose(9.8), 2.4)["reason"] == "stopping"
            assert trip.decide(pose(9.8), 2.9)["reason"] == "arrived"
