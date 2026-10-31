import pytest

from scripts.pilot.route_masks import capture_exclusions, excluded_rectangles


VEHICLE = dict(config=dict(profile=dict(mode='vehicle_buttons')))


def excluded(point, rectangles):
    x, y = point
    return any(a <= x <= c and b <= y <= d for a, b, c, d in rectangles)


def test_vehicle_hud_excludes_brake_radar_and_camera_icons_but_keeps_facades():
    rectangles = capture_exclusions('game', VEHICLE)
    for point in ((.824, .887), (.931, .887), (.16, .29), (.9, .435), (.28, .9), (.28,.64)):
        assert excluded(point, rectangles)
    for point in ((.5, .4), (.45, .65), (.7, .5)):
        assert not excluded(point, rectangles)


def test_vehicle_without_hud_keeps_buildings_and_removes_mirrors_and_footer():
    rectangles = capture_exclusions('avatar', VEHICLE)
    assert excluded((.3, .82), rectangles)
    assert excluded((.6, .99), rectangles)
    assert not excluded((.9, .4), rectangles)
    assert not excluded((.5, .55), rectangles)


def test_walking_and_explicit_unmasked_capture_keep_existing_policy():
    for mode in ('none', 'avatar', 'game'):
        assert capture_exclusions(mode, {}) == excluded_rectangles(mode)
        assert capture_exclusions(mode, dict(config=dict(profile=dict(mode='stick')))) == excluded_rectangles(mode)
    assert capture_exclusions('none', VEHICLE) == ()
    with pytest.raises(ValueError):
        capture_exclusions('unknown', VEHICLE)
