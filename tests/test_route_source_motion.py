"""Piecewise source-clock envelope fixtures; no replay, inference or refitting."""

import numpy as np
import pytest

from motor_worker.route_confirmation import source_arc_motion_envelope


def test_initial_subpixel_arc_jitter_includes_recorded_departure_preimage():
    arc = np.array([0., .00005, .0001, .00015, .0002, .4502, .9002])
    times = np.arange(len(arc)) * .2
    result = source_arc_motion_envelope(arc, times, .0001, .004, .1)
    assert result is not None
    assert result["arc_low"] == 0
    assert result["source_first"] == 0
    # A single nearest source timestamp would be .4s and miss departure.
    assert .8 < result["source_last"] < 1.
    assert result["speed"] == pytest.approx(2.25)
    assert result["limit"] == pytest.approx(2.25 * .2 * 1.25)


def test_complete_long_pause_is_retained_without_inventing_a_source_gap():
    arc = np.array([0., 1., 1., 1., 1., 1., 1., 1., 1., 2., 3.])
    times = np.arange(len(arc)) * .5
    result = source_arc_motion_envelope(arc, times, 1., .01, .2)
    assert result is not None
    assert result["source_first"] == pytest.approx(.495)
    assert result["source_last"] == pytest.approx(4.005)
    assert result["window_start"] == 0
    assert result["window_end"] == pytest.approx(4.505)
    assert result["speed"] == pytest.approx(2.)
    assert result["limit"] == pytest.approx(.5)


def test_far_away_fast_section_cannot_inflate_local_limit():
    times = np.arange(21) * .5
    arc = times.copy()
    arc[-2:] = [109., 209.]
    result = source_arc_motion_envelope(arc, times, 1., .05, .2)
    assert result is not None
    assert result["window_start"] == pytest.approx(.45)
    assert result["window_end"] == pytest.approx(1.55)
    assert result["speed"] == pytest.approx(1.)
    assert result["limit"] == pytest.approx(.25)


@pytest.mark.parametrize("progress,low,high,first,last,start,end", [
    (0., 0., .1, 0., .05, 0., .55),
    (3., 2.9, 3., 1.45, 1.5, .95, 1.5),
])
def test_exact_arc_endpoints_clip_source_and_window(progress, low, high, first, last, start, end):
    result = source_arc_motion_envelope([0., 1., 2., 3.], [0., .5, 1., 1.5],
                                        progress, .1, .2)
    assert result is not None
    expected = dict(arc_low=low, arc_high=high, source_first=first, source_last=last,
                    window_start=start, window_end=end, speed=2., limit=.5)
    assert result == pytest.approx(expected)


def test_source_gap_inside_arc_preimage_refuses():
    assert source_arc_motion_envelope([0., 1., 2., 3.], [0., .5, 2., 2.5],
                                      1.5, .05, .2) is None


def test_source_gap_only_in_padded_window_also_refuses():
    assert source_arc_motion_envelope([0., 1., 2., 3., 4.], [0., .5, 1., 2.1, 2.6],
                                      1., .01, .2) is None


def test_closed_window_boundary_cannot_step_over_a_source_gap():
    # Arc preimage ends at .5s, padded window at1.0s. The gap STARTS at1.0s.
    assert source_arc_motion_envelope([0., .5, 1., 2.], [0., .5, 1., 2.1],
                                      .25, .25, .2) is None


def test_distant_source_gap_does_not_poison_observed_local_window():
    result = source_arc_motion_envelope([0., .5, 1., 1.5, 2., 3.],
                                        [0., .5, 1., 1.5, 2., 4.], .5, .01, .2)
    assert result is not None and result["speed"] == pytest.approx(1.)


@pytest.mark.parametrize("dt,horizon", [(.01, .2), (.1, .2), (.2, .2), (.4, .4)])
def test_actual_receiver_dt_and_original_minimum_horizon_are_unchanged(dt, horizon):
    result = source_arc_motion_envelope([0., 1., 2., 3.], [0., .5, 1., 1.5],
                                        1.5, .01, dt)
    assert result is not None
    assert result["limit"] == pytest.approx(2. * horizon * 1.25)


@pytest.mark.parametrize("cadence", [.25, .5, 1.])
def test_uniform_resampling_of_same_source_motion_preserves_envelope(cadence):
    times = np.arange(0, 8. + cadence / 2, cadence)
    result = source_arc_motion_envelope(times.copy(), times, 3.1, .1, .1)
    assert result == pytest.approx(dict(arc_low=3., arc_high=3.2,
        source_first=3., source_last=3.2, window_start=2.5, window_end=3.7,
        speed=1., limit=.25))


@pytest.mark.parametrize("scale", [.1, 3.7, 100.])
def test_positive_sim3_path_distances_scale_limits_but_preserve_source_window(scale):
    path = np.array([[0., 0., 0.], [1., 0., 0.], [1., 0., 0.],
                     [1., 1., 0.], [2., 1., 1.], [3., 1., 1.]])
    q = np.array([[0., -1., 0.], [.6, 0., -.8], [.8, 0., .6]])
    transformed = scale * path @ q.T + [7., -3., 11.]
    arc = np.r_[0., np.linalg.norm(np.diff(path, axis=0), axis=1).cumsum()]
    changed_arc = np.r_[0., np.linalg.norm(np.diff(transformed, axis=0), axis=1).cumsum()]
    times = np.arange(len(path)) * .5
    original = source_arc_motion_envelope(arc, times, 1., .01, .2)
    changed = source_arc_motion_envelope(changed_arc, times, scale, scale * .01, .2)
    assert original is not None and changed is not None
    for key in ("source_first", "source_last", "window_start", "window_end"):
        assert changed[key] == pytest.approx(original[key], abs=1e-12)
    for key in ("arc_low", "arc_high", "speed", "limit"):
        assert changed[key] == pytest.approx(scale * original[key], rel=1e-12)


@pytest.mark.parametrize("arc,times,progress,epsilon,dt", [
    ([0., float("nan"), 2.], [0., .5, 1.], 1., .01, .2),
    ([0., 1., 2.], [0., float("nan"), 1.], 1., .01, .2),
    ([0., 2., 1.], [0., .5, 1.], 1., .01, .2),
    ([0., 1., 2.], [0., .5, .5], 1., .01, .2),
    ([0.], [0.], 0., .01, .2),
    ([0., 0., 0.], [0., .5, 1.], 0., .01, .2),
    ([0., 1., 2.], [0., .5, 1.], -.01, .01, .2),
    ([0., 1., 2.], [0., .5, 1.], 2.01, .01, .2),
    ([0., 1., 2.], [0., .5, 1.], float("nan"), .01, .2),
    ([0., 1., 2.], [0., .5, 1.], True, .01, .2),
    ([0., 1., 2.], [0., .5, 1.], "1", .01, .2),
    ([0., 1., 2.], [0., .5, 1.], 1., 0., .2),
    ([0., 1., 2.], [0., .5, 1.], 1., .01, 0.),
])
def test_invalid_geometry_clock_or_scalar_inputs_refuse(arc, times, progress, epsilon, dt):
    assert source_arc_motion_envelope(arc, times, progress, epsilon, dt) is None


def test_source_arrays_remain_unchanged():
    arc, times = np.array([0., 1., 2.]), np.array([0., .5, 1.])
    old_arc, old_times = arc.copy(), times.copy()
    source_arc_motion_envelope(arc, times, 1., .01, .2)
    np.testing.assert_array_equal(arc, old_arc)
    np.testing.assert_array_equal(times, old_times)
