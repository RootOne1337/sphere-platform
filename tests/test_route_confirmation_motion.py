"""Synthetic actual-PnP regression for the separate subpixel temporal gate."""
import uuid
from dataclasses import replace

import numpy as np

from motor_worker.policy import PolicyFrame
from motor_worker.route_confirmation import _BoundedConfirmationMixin
from motor_worker.route_localization import RouteLocalizer
from tests.test_motor_route_localization import SparseLocalizationTests


class WindowedPnP(_BoundedConfirmationMixin, RouteLocalizer):
    def _rank_proposals(self, proposals):
        assert self._solving_current and not self._subpixel_allowance
        if self.previous is not None:
            limit = self._motion_limit(self.previous[2], self.last_received-self.previous[3])
            self.rank_limits.append(limit)
            assert 'motionAllowanceUnits' not in self.last_diagnostic
        return super()._rank_proposals(proposals)


def measured(cls):
    source = SparseLocalizationTests('test_blank_real_rgb_has_no_pose')
    source.setUp()
    route = replace(source.route, camera_trace=tuple((0., 0., z) for z in
                    (0., .0001, .0002, .0003, 5., 10., 15., 20.)))
    now = [10.]
    epoch, episode, goal = (str(uuid.uuid4()) for _ in range(3))
    value = cls(route, capture_epoch=epoch, episode_id=episode, goal_revision=goal, clock=lambda:now[0])
    value.rank_limits = []
    center = [np.zeros(3)]

    def features(frame):
        pixels = value.cv.projectPoints(source.xyz, np.zeros(3), -center[0], value.K, None)[0].reshape(-1, 2)
        keep = ((pixels[:, 0] >= 1) & (pixels[:, 0] < 959)
                & (pixels[:, 1] >= 1) & (pixels[:, 1] < 539))
        return pixels[keep], source.desc[keep]

    value._features = features
    return value, center, now


def query(value, now, sequence):
    frame = PolicyFrame(value.epoch, sequence, now[0], 960, 540, bytes([sequence])*(960*540*3))
    return value.observe(frame, episode_id=value.episode, goal_revision=value.goal, scene='active')


def test_actual_verified_tiny_motion_crosses_idle_numeric_limit_without_changing_ranking():
    old, old_center, old_now = measured(RouteLocalizer)
    assert query(old, old_now, 1).state == 'confirming'
    old_now[0] += .1
    old_center[0] = np.array([.0003, 0., 0.])
    assert query(old, old_now, 2).reason == 'route_pose_discontinuity'
    value, center, now = measured(WindowedPnP)
    for sequence in range(1, 4):
        center[0] = np.array([.0003*(sequence-1), 0., 0.])
        result = query(value, now, sequence)
        now[0] += .1
    assert result.state == 'localized' and result.inliers >= 20
    assert value.last_diagnostic['motionSubpixelEligible'] is True
    assert value.last_diagnostic['motionCenterDeltaUnits'] > value.last_diagnostic['motionBaseLimitUnits']
    assert value.last_diagnostic['motionCenterDeltaUnits'] <= value.last_diagnostic['motionLimitUnits']
    assert all(limit < .0003 for limit in value.rank_limits)
    assert not value._subpixel_allowance and not value._verified_current


def test_large_source_unit_jump_is_not_repaired_by_subpixel_policy():
    value, center, now = measured(WindowedPnP)
    query(value, now, 1)
    now[0] += .1
    center[0] = np.array([3., 0., 0.])
    result = query(value, now, 2)
    assert result.state == 'unknown' and result.reason == 'route_pose_discontinuity'
    assert value.last_diagnostic['motionSubpixelEligible'] is False
    assert not value._confirmation.votes


def test_cross_axis_translation_cannot_evade_the_euclidean_source_unit_cap():
    value, center, now = measured(WindowedPnP)
    query(value, now, 1)
    now[0] += .1
    center[0] = np.array([.04, .04, 0.])
    result = query(value, now, 2)
    cap = value.last_diagnostic['motionSubpixelCapUnits']
    assert np.max(np.abs(center[0])) < cap < np.linalg.norm(center[0])
    assert value.last_diagnostic['motionSubpixelEligible'] is False
    # A legitimate source-speed envelope is a different, measured permission;
    # this test checks that axis-wise comparison never grants the noise cap.
    assert result.state == 'confirming'
    np.testing.assert_allclose(result.center, center[0], atol=1e-5)


def test_equivalent_but_unretained_winner_cannot_borrow_other_candidate_correspondences():
    value, center, now = measured(WindowedPnP)
    query(value, now, 1)
    original = value._rank_proposals

    def unretained(proposals):
        picked = original(proposals)
        return (picked[0].copy(), picked[1].copy(), *picked[2:])

    value._rank_proposals = unretained
    now[0] += .1
    center[0] = np.array([.0003, 0., 0.])
    result = query(value, now, 2)
    assert result.reason == 'route_pose_discontinuity'
    assert value.last_diagnostic['motionSubpixelEligible'] is False


def test_ambiguous_nearest_route_still_rejects_even_when_current_pnp_is_strong():
    value, _, now = measured(WindowedPnP)
    query(value, now, 1)
    now[0] += .1
    value._nearest = lambda center: None
    result = query(value, now, 2)
    assert result.state == 'unknown' and result.reason == 'route_progress_ambiguous'
    assert result.center is None and not value._confirmation.votes


def test_current_missing_and_expired_observations_cannot_use_last_subpixel_permission():
    value, center, now = measured(WindowedPnP)
    for sequence in range(1, 4):
        center[0] = np.array([.0003*(sequence-1), 0., 0.])
        query(value, now, sequence)
        now[0] += .1
    value._features = lambda frame: (np.empty((0, 2)), np.empty((0, 128)))
    missed = query(value, now, 4)
    assert missed.state == 'unknown' and missed.center is None
    now[0] += .1
    value.clock = lambda: now[0]+.3
    stale = query(value, now, 5)
    assert stale.state == 'unknown' and not value._confirmation.votes
    assert not value._subpixel_allowance
