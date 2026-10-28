from scripts.pilot.route_temporal_repair import needs_repair


def geometry(xs):
    return {'cameras':[{'image':f'{i:08}.png','ticks_90k':i*45000,'center':[x,0.,0.]}
                       for i,x in enumerate(xs)]}


def test_complete_stable_route_does_not_spend_a_second_reconstruction():
    assert not needs_repair(geometry([0,1,2,3,4]),5)


def test_missing_views_and_false_reverse_motion_trigger_automatic_repair():
    assert needs_repair(geometry([0,1,2,3]),5)
    assert needs_repair(geometry([0,1,2,1,2,3]),6)
    assert needs_repair(geometry([0,1,2,3,4,34,35]),7)
