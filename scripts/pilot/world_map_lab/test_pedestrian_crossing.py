import numpy as np

from scripts.pilot.world_map_lab.pedestrian_crossing import crossing_target, verified_crossings


def street(a, b, *, samples, wall=False, gap=False):
    profile = []
    for x, y, z in np.linspace(a, b, samples):
        road = abs(x) < 4 and abs(y) < 35
        pavement = (4 <= abs(x) <= 8 or abs(y) >= 35) and not (gap and y > 0)
        profile.append(
            dict(
                floor=0,
                referenceZ=z,
                water=None,
                road=0 if road else None,
                paving=0 if pavement else None,
            )
        )
    return dict(profile=profile, bodyIntersections=int(wall))


def test_transverse_crossing_and_pavement_only():
    path = np.array([[-6, 0, 0], [0, 0, 0], [6, 0, 0]])
    crossing = verified_crossings(path, street)
    assert crossing and len(crossing) == 1
    assert crossing[0]["entry"][0] <= -4 and crossing[0]["exit"][0] >= 4
    assert verified_crossings(np.array([[-6, 0, 0], [-6, 4, 0]]), street) == []


def test_reject_longitudinal_travel_a_diagonal_wall_and_unmarked_exit():
    assert verified_crossings(np.array([[0, -37, 0], [0, 37, 0]]), street) is None
    assert verified_crossings(np.array([[-5, -10, 0], [5, 10, 0]]), street) is None
    assert verified_crossings(np.array([[-5, 0, 0], [0, 0, 0]]), street) is None
    road = np.array([[-6, -1, 0], [6, 1, 0]])
    assert verified_crossings(road, lambda a, b, **kw: street(a, b, wall=True, **kw)) is None
    assert verified_crossings(road, lambda a, b, **kw: street(a, b, gap=True, **kw)) is None


def test_crossing_command_stays_between_verified_curbs():
    entry, exit = [-4.1, 0, 0], [4.1, 0, 0]
    assert np.allclose(crossing_target([-4.4, 0, 0], entry, exit, street), exit)
    assert np.allclose(crossing_target([0, 0.28, 0], entry, exit, street), exit)
    assert crossing_target([0, 1.1, 0], entry, exit, street) is None
    assert crossing_target([5, 0, 0], entry, exit, street) is None
    assert (
        crossing_target([0, 0, 0], entry, exit, lambda a, b, **kw: street(a, b, wall=True, **kw))
        is None
    )


def test_driveway_ends_before_a_continuous_street():
    def driveway(a, b, *, samples):
        result = street(a, b, samples=samples)
        for point, row in zip(np.linspace(a, b, samples), result["profile"]):
            if point[1] > 6:
                row["road"] = None
        return result

    path = np.array([[-6, 0, 0], [0, 0, 0], [6, 0, 0]])
    assert verified_crossings(path, driveway) is None
