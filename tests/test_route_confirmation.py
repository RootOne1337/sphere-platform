"""Temporal evidence tests; synthetic PnP fixtures are not gameplay acceptance."""
import hashlib
import uuid

import numpy as np
import pytest

from motor_worker.policy import PolicyFrame
from motor_worker.protocol import ProtocolError
from motor_worker.route_confirmation import (
    ConfirmationEvidence,
    ReferenceLKConfirmationLocalizer,
    _BoundedConfirmationMixin,
)
from motor_worker.route_localization import RouteLocalizer
from tests.test_motor_route_localization import SparseLocalizationTests
from tests.test_route_reference_lk import loaded


class WindowedSparse(_BoundedConfirmationMixin, RouteLocalizer):
    """Use the unchanged core solver/gates with a controlled PnP fixture."""

    def close(self):
        self._confirmation.clear()


def tracker(cls):
    fixture = SparseLocalizationTests('test_blank_real_rgb_has_no_pose')
    fixture.setUp()
    now = [10.]
    epochs = [str(uuid.uuid4()) for _ in range(3)]
    value = cls(fixture.route, capture_epoch=epochs[0], episode_id=epochs[1], goal_revision=epochs[2], clock=lambda: now[0])
    # Actual core PnP verifies measured synthetic 3D->2D projection; only the
    # presence of correspondences is controlled to model a missed observation.
    cv = value.cv
    xyz = value.np.asarray(fixture.route.points)
    pixels = cv.projectPoints(xyz, np.zeros(3), np.zeros(3), value.K, None)[0].reshape(-1, 2)
    visible = ((pixels[:, 0] >= 1) & (pixels[:, 0] < 959)
               & (pixels[:, 1] >= 1) & (pixels[:, 1] < 539))
    xyz, pixels = xyz[visible], pixels[visible]
    verified = value._verify_correspondences(xyz, pixels)
    assert verified is not None
    good = [True]
    value._features = lambda frame: ((), ())
    value._solve = lambda *unused: verified[:4] if good[0] else None
    return value, now, epochs, good


def observe(value, now, epochs, sequence, *, good=None, repeat=None, scene='active'):
    raw = bytes([sequence % 251 if repeat is None else repeat]) * (960 * 540 * 3)
    frame = PolicyFrame(epochs[0], sequence, now[0], 960, 540, raw)
    return value.observe(frame, episode_id=epochs[1], goal_revision=epochs[2], scene=scene)


def test_old_fsm_never_acquires_alternating_valid_and_missed_pnp():
    value, now, epochs, good = tracker(RouteLocalizer)
    states = []
    for sequence in range(1, 10):
        good[0] = sequence % 2 == 1
        states.append(observe(value, now, epochs, sequence).state)
        now[0] += .1
    assert states == ['confirming', 'unknown'] * 4 + ['confirming']


def test_three_distinct_valid_of_five_acquire_and_current_miss_stays_unknown():
    value, now, epochs, good = tracker(WindowedSparse)
    poses = []
    for sequence in range(1, 7):
        good[0] = sequence % 2 == 1
        poses.append(observe(value, now, epochs, sequence))
        now[0] += .1
    assert [pose.state for pose in poses] == ['confirming', 'unknown', 'confirming', 'unknown', 'localized', 'unknown']
    assert poses[-1].center is None and poses[-1].polyline_px == ()


def test_repeated_rgb_never_votes_or_republishes_old_pose():
    value, now, epochs, _ = tracker(WindowedSparse)
    states = []
    for sequence in range(1, 9):
        states.append(observe(value, now, epochs, sequence, repeat=1))
        now[0] += .1
    assert states[0].state == 'confirming'
    assert all(pose.reason == 'route_repeated_rgb_not_independent' and pose.state == 'unknown' for pose in states[1:])
    assert len(value._confirmation.votes) == 0


def test_single_duplicate_between_three_distinct_images_is_not_a_new_vote():
    value, now, epochs, _ = tracker(WindowedSparse)
    poses = []
    for sequence, gray in enumerate([1, 1, 2, 2, 3], 1):
        poses.append(observe(value, now, epochs, sequence, repeat=gray))
        now[0] += .1
    assert [pose.state for pose in poses] == ['confirming', 'unknown', 'confirming', 'unknown', 'localized']


def test_isolated_valids_do_not_accumulate_outside_five_observations():
    value, now, epochs, good = tracker(WindowedSparse)
    for sequence in range(1, 14):
        good[0] = sequence % 4 == 1
        pose = observe(value, now, epochs, sequence)
        now[0] += .1
        assert pose.state != 'localized'


def test_more_than_one_second_expires_old_votes():
    window = ConfirmationEvidence()
    for sequence, received in [(1, 10.), (2, 10.2), (3, 11.21)]:
        window.prepare(('epoch',), sequence, received)
        window.append(hashlib.sha256(str(sequence).encode()).hexdigest(), valid=True)
    assert len(window.votes) == 1


@pytest.mark.parametrize('kind', ['stale', 'gap', 'menu', 'epoch', 'goal'])
def test_hard_boundaries_clear_evidence(kind):
    value, now, epochs, good = tracker(WindowedSparse)
    for sequence in [1, 2]:
        observe(value, now, epochs, sequence)
        now[0] += .1
    if kind == 'stale':
        value.clock = lambda: now[0] + .3
    if kind == 'gap':
        now[0] += .6
    if kind == 'epoch':
        epochs[0] = str(uuid.uuid4())
    if kind == 'goal':
        epochs[2] = str(uuid.uuid4())
    pose = observe(value, now, epochs, 3, scene='menu' if kind == 'menu' else 'active')
    assert pose.state == 'unknown'
    assert len(value._confirmation.votes) == 0


def test_unchanged_motion_jump_gate_clears_evidence():
    value, now, epochs, _ = tracker(WindowedSparse)
    observe(value, now, epochs, 1)
    now[0] += .1
    value._solve = lambda *unused: (np.array([0., 0., 20.]), np.eye(3), 100, .1)
    pose = observe(value, now, epochs, 2)
    assert pose.state == 'unknown' and pose.reason in {'route_pose_discontinuity', 'route_progress_ambiguous'}
    assert not value._confirmation.votes


def test_nonmonotonic_observation_never_reuses_votes():
    value, now, epochs, _ = tracker(WindowedSparse)
    observe(value, now, epochs, 1)
    with pytest.raises(ProtocolError):
        observe(value, now, epochs, 1)
    assert not value._confirmation.votes
    now[0] += .1
    assert observe(value, now, epochs, 2).reason == 'route_binding_retired'


def test_real_typed_reference_constructor_preserves_artifact_pipeline_and_cache(tmp_path):
    route, _, _ = loaded(tmp_path)
    pipeline = route.pipeline_sha256
    value = ReferenceLKConfirmationLocalizer(route, capture_epoch=str(uuid.uuid4()), episode_id=str(uuid.uuid4()), goal_revision=str(uuid.uuid4()))
    try:
        assert value.route.pipeline_sha256 == pipeline
        assert value.confirmation_policy in value.verification_policy
        assert len(value.confirmation_runtime_sha256) == 64
    finally:
        value.close()
        route.close()
