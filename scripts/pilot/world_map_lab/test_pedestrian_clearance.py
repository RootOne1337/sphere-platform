from scripts.pilot.world_map_lab.pedestrian_clearance import jumpable


def test_only_a_low_narrow_barrier_with_ground_and_clear_landing_can_be_jumped():
    ground = [dict(floor=11.0, referenceZ=11.0, water=None)]
    hedge = dict(
        bodyIntersections=2, blockedFrom=0.5, blockedTo=1.2, blockingHeight=0.65, profile=ground
    )
    clear = dict(bodyIntersections=0, profile=ground)
    assert jumpable(hedge, clear)
    assert not jumpable({**hedge, "blockingHeight": 1.875}, clear)
    assert not jumpable({**hedge, "blockedTo": 2.5}, clear)
    assert not jumpable(hedge, {**clear, "bodyIntersections": 1})
    assert not jumpable(hedge, {**clear, "profile": [dict(floor=8.0, referenceZ=11.0, water=None)]})
    assert not jumpable(
        hedge, {**clear, "profile": [dict(floor=11.0, referenceZ=11.0, water=11.2)]}
    )
