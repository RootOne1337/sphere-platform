import hashlib
import json
import math

import pytest

from scripts.pilot.route_masks import (
    LEGACY_SCOOTER_POLICY,
    PRECISE_FOREGROUND,
    PRECISE_SCOOTER_POLICY,
    VEHICLE_BODY,
    VEHICLE_HUD,
    VEHICLE_MIRROR,
    WATERMARK,
    capture_exclusions,
    capture_mask_plan,
    excluded_rectangles,
)

VEHICLE = dict(config=dict(profile=dict(mode='vehicle_buttons', hudProfile='black_russia_scooter_v1')))


def excluded(point, rectangles):
    x, y = point
    return any(a <= x <= c and b <= y <= d for a, b, c, d in rectangles)


def test_vehicle_hud_excludes_brake_radar_and_camera_icons_but_keeps_facades():
    rectangles = capture_exclusions('game', VEHICLE)
    for point in ((.824, .887), (.931, .887), (.16, .29), (.9, .435), (.28, .9)):
        assert excluded(point, rectangles)
    for point in ((.5, .4), (.45, .65), (.7, .5), (.28, .64), (.5, .15), (.80, .45), (.15, .50)):
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


@pytest.mark.parametrize('profile', [{}, {'hudProfile': 'another_game_v1'}])
def test_unidentified_vehicle_does_not_inherit_black_russia_hud_rectangles(profile):
    manifest = dict(config=dict(profile=dict(mode='vehicle_buttons', **profile)))
    rectangles = capture_exclusions('game', manifest)
    assert rectangles == excluded_rectangles('avatar')
    assert not excluded((.16, .29), rectangles)
    assert not excluded((.9, .435), rectangles)
    assert excluded((.5, .85), rectangles)
    assert capture_exclusions('none', manifest) == ()


def test_explicit_legacy_policy_reproduces_old_exclusions_without_relabeling():
    assert capture_exclusions('game', VEHICLE, policy_id=LEGACY_SCOOTER_POLICY) == (
        *VEHICLE_HUD, VEHICLE_BODY, VEHICLE_MIRROR, WATERMARK)
    assert capture_exclusions('avatar', VEHICLE, policy_id=LEGACY_SCOOTER_POLICY) == (
        VEHICLE_BODY, VEHICLE_MIRROR, WATERMARK)
    old = capture_mask_plan('game', VEHICLE, policy_id=LEGACY_SCOOTER_POLICY)
    new = capture_mask_plan('game', VEHICLE)
    assert old['policy_id'] == LEGACY_SCOOTER_POLICY
    assert new['policy_id'] == PRECISE_SCOOTER_POLICY
    assert old['sha256'] != new['sha256']
    assert capture_exclusions('none', VEHICLE, policy_id=LEGACY_SCOOTER_POLICY) == ()


def test_precise_controls_cover_measured_ellipse_edges_and_six_pixel_padding():
    rectangles = capture_exclusions('game', VEHICLE)
    ellipses = ((158,160,156,153), (112,600,61,63), (287,880,150,150),
                (1622,465,48,48), (1745,465,48,48), (1868,465,48,48),
                (1807,608,79,79), (1807,774,79,79),
                (1577,953,82,84), (1805,953,82,84))
    for cx, cy, rx, ry in ellipses:
        for degree in range(360):
            angle = math.radians(degree)
            nx, ny = math.cos(angle)/rx, math.sin(angle)/ry
            length = math.hypot(nx, ny)
            x = cx+rx*math.cos(angle)+6*nx/length
            y = cy+ry*math.sin(angle)+6*ny/length
            if 0 <= x < 1920 and 0 <= y < 1080:
                assert excluded((x/1920, y/1080), rectangles), (cx,cy,degree)


def test_mask_plan_is_deterministic_bounded_and_separates_unknown_foreground():
    plan = capture_mask_plan('game', VEHICLE)
    assert plan == capture_mask_plan('game', VEHICLE)
    assert len(plan['excluded_rectangles']) == 16
    assert plan['foreground_rectangles'] == [list(rect) for rect in PRECISE_FOREGROUND]
    assert plan['dynamic_foreground_coverage'] == 'unknown'
    assert plan['execution_qualified'] is False
    body = {key:value for key,value in plan.items() if key != 'sha256'}
    assert plan['sha256'] == hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    for a,b,c,d in plan['excluded_rectangles']:
        assert 0 <= a < c <= 1 and 0 <= b < d <= 1
    with pytest.raises(ValueError, match='invalid_capture_mask_policy'):
        capture_mask_plan('game', VEHICLE, policy_id='not-a-policy')
    with pytest.raises(ValueError, match='capture_mask_policy_capture_mismatch'):
        capture_mask_plan('game', {}, policy_id=PRECISE_SCOOTER_POLICY)


def test_sealed_old_profile_stays_byte_identical_and_valid_after_new_plan_selection():
    from motor_worker.landmarks import RouteViewProfile
    from motor_worker.route_localization import feature_mask

    old = RouteViewProfile('f6b07080-9380-40d9-90e8-b4405924c8cb', 1920, 1080,
                          (0.,0.,1.,1.), capture_exclusions('game', VEHICLE,
                                                        policy_id=LEGACY_SCOOTER_POLICY))
    encoded = old.encode()
    before = feature_mask(old).tobytes()
    new = RouteViewProfile('eb77e996-43de-4f9e-acef-1024ed4c6428', 1920, 1080,
                          (0.,0.,1.,1.), capture_exclusions('game', VEHICLE))
    assert RouteViewProfile.parse(new.encode()) == new
    restored = RouteViewProfile.parse(encoded)
    assert restored.encode() == encoded
    assert feature_mask(restored).tobytes() == before
    assert hashlib.sha256(before).hexdigest() == '4fc84e852a6d26135c22a84e1f8cf86959f79ccf361c1db675911c29659580b2'
    assert (feature_mask(new) != 0).sum() > 1.5*(feature_mask(restored) != 0).sum()
