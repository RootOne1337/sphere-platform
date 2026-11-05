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


def test_vehicle_keeps_temporal_overlap_even_when_static_hud_reduces_median_flow():
    rows=[dict(index=i,relative_ticks_90k=i*3600) for i in range(901)]
    old,_=select_motion_rows(rows,{})
    vehicle,report=select_motion_rows(rows,{},vehicle=True)
    assert len(vehicle)>len(old) and len(vehicle)<=240
    assert min(vehicle)==0 and max(vehicle)==900
    assert max(b-a for a,b in zip(sorted(vehicle),sorted(vehicle)[1:]))*3600/90000<=.24
    assert report['vehicleOverlap'] is True and report['posesUsed'] is False


@pytest.mark.parametrize(('destination_x', 'measured'), [(14., 1), (40., 0), (70., 0)])
def test_motion_sampling_excludes_tracks_entering_hud_or_leaving_frame(monkeypatch, destination_x, measured):
    from types import SimpleNamespace

    cv = pytest.importorskip('cv2')
    np = pytest.importorskip('numpy')
    from motor_worker import browser_teach
    from scripts.pilot import route_mask_raster, route_motion_sampling

    rows = [dict(index=0, relative_ticks_90k=0), dict(index=1, relative_ticks_90k=3000)]
    capture = SimpleNamespace(geometry=(64, 36), manifest={}, frames=rows)
    frame = SimpleNamespace(to_ndarray=lambda **_: np.zeros((36, 64), np.uint8))
    mask = np.full((36, 64), 255, np.uint8)
    mask[:, 32:] = 0
    points = np.array([(10., y) for y in range(8, 23)], dtype=np.float32).reshape(-1, 1, 2)
    moved = points[:, 0].copy()
    moved[:, 0] = destination_x
    monkeypatch.setattr(browser_teach, 'decoded_browser', lambda _: ((row, frame) for row in rows))
    monkeypatch.setattr(route_mask_raster, 'reconstruction_mask', lambda *_: mask)
    monkeypatch.setattr(cv, 'goodFeaturesToTrack', lambda *_, **__: points)
    monkeypatch.setattr(route_motion_sampling, 'track_source_points',
                        lambda *_, **__: (moved, np.ones(len(points), dtype=bool)))

    _, report = route_motion_sampling.sample_video(capture, 'game', lambda: None)
    assert report['scoresMeasured'] == measured
