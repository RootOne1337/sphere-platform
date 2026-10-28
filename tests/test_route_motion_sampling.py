import pytest
from scripts.pilot.route_motion_sampling import select_motion_rows


def test_extra_views_follow_image_motion_without_spending_views_on_static_video():
    rows=[dict(index=i,relative_ticks_90k=i*3000) for i in range(301)]
    sparse,report=select_motion_rows(rows,{})
    rapid={i:8. for i in range(90,121)}
    adaptive,_=select_motion_rows(rows,rapid)
    assert 0 in adaptive and 300 in adaptive
    assert len(adaptive)>len(sparse)
    assert len([i for i in adaptive if 90<=i<=120])>len([i for i in sparse if 90<=i<=120])
    assert report['posesUsed'] is False and report['metricScaleKnown'] is False


def test_large_motion_cannot_exceed_the_declared_camera_budget():
    rows=[dict(index=i,relative_ticks_90k=i*3000) for i in range(1800)]
    selected,_=select_motion_rows(rows,{i:50. for i in range(1800)},max_images=120)
    assert len(selected)<=120 and min(selected)==0 and max(selected)==1799
    with pytest.raises(ValueError,match='motion_sampling_score'):
        select_motion_rows(rows,{1:float('nan')})
