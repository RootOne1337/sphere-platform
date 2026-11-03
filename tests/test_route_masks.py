import hashlib
import json
import math

import pytest

from scripts.pilot.route_masks import (
    LEGACY_SCOOTER_POLICY,
    PRECISE_FOREGROUND,
    PRECISE_SCOOTER_POLICY,
    PRECISE_SCOOTER_V2_POLICY,
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


@pytest.mark.parametrize('policy,mode,expected', [
    (LEGACY_SCOOTER_POLICY, 'none', '9567aeccc6e6577cc4b0cb1ba4f9e0bc1c7c9fb25f06c3576bd61bad0d2cca00'),
    (LEGACY_SCOOTER_POLICY, 'avatar', 'ff68018599cfd218b7b677adae139188f2bf079fa4efc568c9200954e706af5a'),
    (LEGACY_SCOOTER_POLICY, 'game', 'f1ccb4fda5a51d769ecf8d1e5b243ee4457304e820ace180106910caf85b5c7a'),
    (PRECISE_SCOOTER_V2_POLICY, 'none', '787d85e884245447ba0ccf51d063638970deac894a08a995da873c014a83e97f'),
    (PRECISE_SCOOTER_V2_POLICY, 'avatar', '62c38c8b271b42cbdd74547f1e14add53892257c5c7c0252c020cc71166904b6'),
    (PRECISE_SCOOTER_V2_POLICY, 'game', '3c9c6ace7e9e34216cb824e46f3ea3b867d23c10ed00559a306fc4234ac7b1f0'),
])
def test_explicit_historical_policies_retain_full_pre_v3_plan_sha(policy, mode, expected):
    assert capture_mask_plan(mode, VEHICLE, policy_id=policy)['sha256'] == expected


def test_v3_closes_observed_logo_gap_without_adding_a_rectangle():
    v2 = capture_exclusions('game', VEHICLE, policy_id=PRECISE_SCOOTER_V2_POLICY)
    v3 = capture_exclusions('game', VEHICLE)
    assert PRECISE_SCOOTER_POLICY == 'black_russia_scooter_precise_rect_v3'
    assert len(v2) == len(v3) == 16
    assert not excluded((.04, .95), v2)
    for point in ((.0,.91), (.04,.95), (.06,.97), (.075,.95)):
        assert excluded(point, v3)
    assert capture_mask_plan('game', VEHICLE)['foreground_rectangles'][2] == [.0,.90,.73,1.]
    for point in ((.04,.88), (.04,.50), (.15,.50), (.5,.4)):
        assert excluded(point, v3) == excluded(point, v2)


def test_v2_stored_runtime_mask_is_exact_and_v3_area_change_stays_local():
    import numpy as np

    from motor_worker.landmarks import RouteViewProfile
    from motor_worker.route_localization import feature_mask

    def profile(policy):
        return RouteViewProfile('f6b07080-9380-40d9-90e8-b4405924c8cb', 1920, 1080,
            (0.,0.,1.,1.), capture_exclusions('game', VEHICLE, policy_id=policy))

    old_profile = profile(PRECISE_SCOOTER_V2_POLICY)
    encoded = old_profile.encode()
    old = feature_mask(RouteViewProfile.parse(encoded))
    new = feature_mask(profile(PRECISE_SCOOTER_POLICY))
    assert hashlib.sha256(old.tobytes()).hexdigest() == '0757b9296f5ebc007faf52382842d81940ffd7d25667ae2f3ed1f0b03edd622d'
    assert old_profile.encode() == encoded
    assert not np.any((old == 0) & (new != 0))
    added = (old != 0) & (new == 0)
    assert 0 < added.mean() < .015
    yy, xx = np.nonzero(added)
    height, width = old.shape  # Runtime masks are 960x540, with an 8px margin.
    assert xx.max() < .08*width and yy.min() >= .88*height
    assert np.array_equal(old[:int(.88*height)], new[:int(.88*height)])
    assert (feature_mask(RouteViewProfile.parse(encoded)) == old).all()


def test_none_and_unknown_profiles_keep_their_previous_exclusions():
    assert capture_exclusions('none', VEHICLE) == ()
    assert capture_exclusions('none', {}) == ()
    assert capture_exclusions('game', {}) == excluded_rectangles('game')
    unknown_vehicle = dict(config=dict(profile=dict(mode='vehicle_buttons', hudProfile='other_game')))
    assert capture_exclusions('game', unknown_vehicle) == excluded_rectangles('avatar')
    assert capture_mask_plan('game', unknown_vehicle)['policy_id'] == 'generic_rect_v1'
