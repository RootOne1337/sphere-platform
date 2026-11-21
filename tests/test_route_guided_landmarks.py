"""Known-pose matching must reject aliases without manufacturing geometry."""

import json
from collections import Counter

import cv2
import numpy as np
import pytest

from scripts.pilot import route_guided_landmarks as builder


def fixture(views=3, *, curved=False):
    k = np.array([[400.0, 0.0, 480.0], [0.0, 400.0, 270.0], [0.0, 0.0, 1.0]])
    points = np.array([[-1.0, 0.0, 7.0], [-0.4, 0.0, 9.0], [0.3, 0.0, 11.0], [0.9, 0.0, 13.0]])
    observations, poses = [], []
    for view in range(views):
        angle = 0.08 * view if curved else 0.0
        rotation = cv2.Rodrigues(np.array([0.0, angle, 0.0]))[0]
        center = np.array([-0.6 + view * 0.6, 0.0, 0.1 * view * view if curved else 0.0])
        pose = np.column_stack((rotation, -rotation @ center))
        projected = (points @ rotation.T + pose[:, 3]) @ k.T
        pixels = projected[:, :2] / projected[:, 2:]
        descriptors = np.zeros((len(points), 128), np.float32)
        for row in range(len(points)):
            descriptors[row, row] = 1
        observations.append((pixels, descriptors))
        poses.append(pose)
    return observations, poses, k, points


def run(data, **kwargs):
    return builder.build(*data[:3], checkpoint=kwargs.pop("checkpoint", lambda: None), **kwargs)


def test_known_curve_retains_true_measured_tracks_without_editing_inputs():
    data = fixture(curved=True)
    before = [(p.tobytes(), d.tobytes()) for p, d in data[0]]
    poses = [p.tobytes() for p in data[1]]
    proof = []
    rows, report = run(data, provenance=proof)
    assert len(rows) == len(data[3])
    np.testing.assert_allclose(np.array([r[1] for r in rows]), data[3], atol=1e-7)
    assert all(r[0] == 3 and r[3] == (0, 1, 2) for r in rows)
    assert before == [(p.tobytes(), d.tobytes()) for p, d in data[0]]
    assert poses == [p.tobytes() for p in data[1]]
    assert len(proof) == len(rows)
    for row, item in zip(rows, proof):
        a, b = item["medoid_observation"]
        np.testing.assert_array_equal(row[2], data[0][a][1][b])
    assert not report["camera_poses_modified"] and not report["intrinsics_modified"]
    assert report["max_view_lag"] == 8 and not report["source_times_used_for_matching"]
    assert not report["execution_qualified"]
    assert "landmark_provenance" not in report and len(json.dumps(report)) < 65536


def test_repeated_facade_global_winner_is_rejected_without_promoting_runner_up():
    data = fixture()
    for view, (pixels, descriptors) in enumerate(data[0]):
        descriptors = descriptors.copy()
        angle = 0.1 * view
        descriptors[0, :2] = [np.cos(angle), np.sin(angle)]
        # The descriptor's nearest candidate in later images is this wrong
        # facade row. Its 40 px vertical displacement contradicts known F.
        false_descriptor = np.zeros((1, 128), np.float32)
        false_descriptor[0, 0] = 1
        data[0][view] = (
            np.vstack((pixels, pixels[0] + [0.0, 40.0])),
            np.vstack((descriptors, false_descriptor)),
        )
    a, b = data[0][:2]
    raw = cv2.BFMatcher(cv2.NORM_L2).knnMatch(a[1], b[1], k=2)
    assert raw[0][0].trainIdx == 4
    proof = []
    rows, report = run(data, provenance=proof)
    assert report["matching"]["epipolar_rejected_global_winners"] > 0
    assert not any(p["observations"] == [[0, 0], [1, 0], [2, 0]] for p in proof)
    assert not any(np.linalg.norm(np.array(row[1]) - data[3][0]) < 1e-6 for row in rows)


def test_ratio_requires_two_global_descriptor_candidates():
    data = fixture()
    observations = [(p[:1], d[:1]) for p, d in data[0]]
    rows, report = builder.build(observations, data[1], data[2], checkpoint=lambda: None)
    assert not rows and report["matching"].get("descriptor_proposals", 0) == 0


def test_valid_global_ratio_does_not_require_ambiguity_competitor_on_epipolar_line():
    k = fixture()[2]
    poses = fixture()[1]
    f = builder._fundamental(poses[0], poses[1], np.linalg.inv(k), 1e-12)
    pixels = np.array([[20.0, 20.0], [20.0, 60.0]])
    descriptors = np.zeros((2, 128), np.float32)
    descriptors[0, 0], descriptors[1, 1] = 1, 1
    counts = Counter()
    selected = builder._directed(
        pixels, descriptors, pixels, descriptors, f, checkpoint=lambda: None, counts=counts
    )
    assert set(selected) == {0, 1}
    assert counts["global_descriptor_gate_passed_queries"] == 2
    assert counts["epipolar_checked_global_winners"] == 2


def test_failed_original_ratio_cannot_be_rescued_by_a_single_geometric_candidate():
    data = fixture()
    f = builder._fundamental(data[1][0], data[1][1], np.linalg.inv(data[2]), 1e-12)
    query = np.zeros((1, 128), np.float32)
    query[0, 0] = 1
    target = np.zeros((2, 128), np.float32)
    for row, angle in enumerate((0.10, 0.11)):
        target[row, :2] = [np.cos(angle), np.sin(angle)]
    counts = Counter()
    selected = builder._directed(
        np.array([[20.0, 20.0]]),
        query,
        np.array([[20.0, 20.0], [20.0, 60.0]]),
        target,
        f,
        checkpoint=lambda: None,
        counts=counts,
    )
    assert selected == {} and counts["global_ratio_rejected_queries"] == 1
    assert counts["epipolar_checked_global_winners"] == 0


def test_valid_original_ratio_with_off_epipolar_winner_never_promotes_second():
    data = fixture()
    f = builder._fundamental(data[1][0], data[1][1], np.linalg.inv(data[2]), 1e-12)
    query = np.zeros((1, 128), np.float32)
    query[0, 0] = 1
    target = np.zeros((2, 128), np.float32)
    for row, angle in enumerate((0.05, 0.30)):
        target[row, :2] = [np.cos(angle), np.sin(angle)]
    counts = Counter()
    selected = builder._directed(
        np.array([[20.0, 20.0]]),
        query,
        np.array([[20.0, 60.0], [20.0, 20.0]]),
        target,
        f,
        checkpoint=lambda: None,
        counts=counts,
    )
    assert selected == {} and counts["global_descriptor_gate_passed_queries"] == 1
    assert counts["epipolar_rejected_global_winners"] == 1


def test_mutual_ratio_and_absolute_descriptor_distance_stay_strict():
    data = fixture()
    data[0][1][1][:] = 0
    data[0][1][1][:, 127] = 1  # Every row has an exact tie and is far away.
    rows, report = run(data)
    assert not rows
    assert report["matching"]["global_ratio_rejected_queries"] > 0


def test_exact_reverse_refuses_a_forward_match_owned_by_a_closer_other_detection():
    data = fixture()
    for view, angles in enumerate(((0.0, 0.05), (0.049, 0.5), (0.048, 0.6))):
        descriptors = np.zeros((2, 128), np.float32)
        for row, angle in enumerate(angles):
            descriptors[row, :2] = [np.cos(angle), np.sin(angle)]
        data[0][view] = (data[0][view][0][:2], descriptors)
    _, report = run(data)
    assert report["matching"]["nonreciprocal_matches_rejected"] > 0


def test_global_two_is_bounded_and_does_not_search_unexamined_geometry_candidates():
    data = fixture()
    f = builder._fundamental(data[1][0], data[1][1], np.linalg.inv(data[2]), 1e-12)
    query = np.zeros((1, 128), np.float32)
    query[0, 0] = 1
    target = np.zeros((10, 128), np.float32)
    for row, angle in enumerate((*np.arange(8) * 0.01, 0.15, 0.35)):
        target[row, :2] = [np.cos(angle), np.sin(angle)]
    pixels_b = np.array([[20.0, 60.0]] * 8 + [[20.0, 20.0], [30.0, 20.0]])
    counts = Counter()
    selected = builder._directed(
        np.array([[20.0, 20.0]]), query, pixels_b, target, f, checkpoint=lambda: None, counts=counts
    )
    assert not selected and counts["descriptor_proposals"] == 2
    assert counts["epipolar_rejected_global_winners"] == 1


def test_conflicting_triangle_is_deterministic_and_never_duplicates_an_image():
    edges = [(0.1, 0.2, 0, 0, 1, 0), (0.2, 0.1, 1, 0, 2, 0), (0.3, 0.0, 0, 1, 2, 0)]
    first, stats = builder._tracks(edges, checkpoint=lambda: None)
    for ordered in (edges[::-1], edges[1:] + edges[:1]):
        assert builder._tracks(ordered, checkpoint=lambda: None) == (first, stats)
    assert [(0, 0), (1, 0), (2, 0)] in first
    assert all(len({view for view, _ in track}) == len(track) for track in first)
    assert stats["conflict_edges_rejected"] == 1


def test_known_f_sampson_is_scale_invariant_and_degenerate_denominator_refuses():
    data = fixture()
    f = builder._fundamental(data[1][0], data[1][1], np.linalg.inv(data[2]), 1e-12)
    a, b = data[0][0][0], data[0][1][0].copy()
    b[0, 1] += 20
    expected = builder._sampson(a, b, f)
    assert expected[0] > 2 and np.max(expected[1:]) < 1e-8
    for factor in (1e-100, -1e100, 0.1):
        np.testing.assert_allclose(builder._sampson(a, b, f * factor), expected, atol=1e-10)
    assert np.isinf(builder._sampson(a, b, np.zeros((3, 3)))).all()
    degenerate = np.zeros((3, 3))
    degenerate[2, 2] = 1
    assert np.isinf(builder._sampson(a, b, degenerate)).all()


def test_zero_baseline_and_pure_rotation_do_not_invent_f():
    data = fixture()
    data[1][1] = np.column_stack((cv2.Rodrigues(np.array([0.0, 0.2, 0.0]))[0], [0.0, 0.0, 0.0]))
    first = np.column_stack((np.eye(3), [0.0, 0.0, 0.0]))
    assert builder._fundamental(first, first, np.linalg.inv(data[2]), 1e-9) is None
    assert builder._fundamental(first, data[1][1], np.linalg.inv(data[2]), 1e-9) is None
    tiny = first.copy()
    tiny[0, 3] = 1e-12
    assert builder._fundamental(first, tiny, np.linalg.inv(data[2]), 1e-9) is None


def test_all_coincident_cameras_produce_no_tracks_or_points():
    data = fixture()
    data[1][:] = [data[1][0].copy() for _ in data[1]]
    rows, report = run(data)
    assert not rows and report["matching"]["zero_or_tiny_baseline_pairs_skipped"] == 3
    assert report["tracks"] == 0


def test_static_pair_can_be_skipped_while_longer_baseline_tracks_survive():
    data = fixture(views=4)
    data[1][1] = data[1][0].copy()
    data[0][1] = tuple(v.copy() for v in data[0][0])
    rows, report = run(data)
    assert len(rows) == 4
    assert report["matching"]["zero_or_tiny_baseline_pairs_skipped"] == 1


def test_low_parallax_is_still_rejected_after_epipolar_matching():
    data = fixture()
    for view in range(3):
        pose = np.column_stack((np.eye(3), [-view * 1e-5, 0.0, 0.0]))
        q = (data[3] + pose[:, 3]) @ data[2].T
        data[1][view] = pose
        data[0][view] = (q[:, :2] / q[:, 2:], data[0][view][1])
    rows, report = run(data)
    assert not rows and report["rejection_reasons"]["parallax_under_1_degree"] == 4


def test_negative_depth_is_still_rejected_after_epipolar_matching():
    data = fixture()
    points = data[3].copy()
    points[:, 2] *= -1
    for view, pose in enumerate(data[1]):
        q = (points @ pose[:, :3].T + pose[:, 3]) @ data[2].T
        data[0][view] = (q[:, :2] / q[:, 2:], data[0][view][1])
    rows, report = run(data)
    assert not rows and report["rejection_reasons"]["nonpositive_depth"] == 4


def test_epipolar_compatible_but_inconsistent_disparity_still_fails_reprojection():
    data = fixture()
    data[0][1][0][0, 0] += 50  # Same epipolar line, inconsistent three-view depth.
    rows, report = run(data)
    assert len(rows) == 3 and report["rejection_reasons"]["reprojection_over_3px"] == 1


@pytest.mark.parametrize("invalid", ["reflection", "nonorthogonal", "nan", "shape"])
def test_invalid_pose_fails_closed(invalid):
    data = fixture()
    if invalid == "reflection":
        data[1][0][0, 0] = -1
    elif invalid == "nonorthogonal":
        data[1][0][0, 0] = 2
    elif invalid == "nan":
        data[1][0][0, 0] = np.nan
    else:
        data[1][0] = np.eye(3)
    with pytest.raises(ValueError, match="pose"):
        run(data)


@pytest.mark.parametrize("invalid", ["nan", "zero_focal", "last_row", "singular", "shape"])
def test_invalid_intrinsics_fails_closed(invalid):
    data = fixture()
    if invalid == "nan":
        data[2][0, 0] = np.nan
    elif invalid == "zero_focal":
        data[2][0, 0] = 0
    elif invalid == "last_row":
        data[2][2, 0] = 1
    elif invalid == "singular":
        data[2][1] = data[2][0]
    else:
        data = (*data[:2], np.eye(2), data[3])
    with pytest.raises(ValueError, match="intrinsics"):
        run(data)


@pytest.mark.parametrize(
    "invalid", ["nan", "shape", "outside", "negative", "normalization", "complex"]
)
def test_invalid_runtime_detections_fail_closed(invalid):
    data = fixture()
    xy, desc = data[0][0]
    if invalid == "nan":
        xy[0, 0] = np.nan
    elif invalid == "shape":
        data[0][0] = (xy[:, :1], desc)
    elif invalid == "outside":
        xy[0, 0] = 960
    elif invalid == "negative":
        desc[0, 0] = -1
    elif invalid == "normalization":
        desc[0, 0] = 0.1
    else:
        data[0][0] = (xy, desc.astype(np.complex128))
    with pytest.raises(ValueError, match="features"):
        run(data)


@pytest.mark.parametrize(
    "constant,error",
    [
        ("MAX_VIEWS", "input_quota"),
        ("MAX_FEATURES_PER_VIEW", "features"),
        ("MAX_OBSERVATIONS", "observation_quota"),
        ("MAX_PAIR_QUERIES", "pair_query_quota"),
        ("MAX_DESCRIPTOR_PROPOSALS", "descriptor_proposal_quota"),
        ("MAX_MATCH_EDGES", "edge_quota"),
    ],
)
def test_count_quotas_refuse_before_returning_any_candidates(monkeypatch, constant, error):
    monkeypatch.setattr(builder, constant, 0)
    with pytest.raises(ValueError, match=error):
        run(fixture())


def test_fixed_lag_eight_never_uses_more_distant_reference_pairs(monkeypatch):
    data = fixture(views=10)
    # Keep points visible in this small matching-scope test.
    data[0][:] = [data[0][0] for _ in data[0]]

    def no_edges(*args, **kwargs):
        return {}

    monkeypatch.setattr(builder, "_directed", no_edges)
    _, report = run(data)
    assert report["matching"]["reference_pairs"] == 44  # all45 pairs minus lag9.


def test_time_quota_and_cancellation_propagate_without_partial_provenance(monkeypatch):
    data = fixture()
    proof = []
    times = iter([0.0, 91.0])
    monkeypatch.setattr(builder.time, "monotonic", lambda: next(times))
    with pytest.raises(ValueError, match="time_quota"):
        run(data, provenance=proof)
    assert proof == []


def test_checkpoint_cancellation_is_not_swallowed():
    def stop():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        run(fixture(), checkpoint=stop)


def test_optional_provenance_quota_refuses_without_partial_external_records(monkeypatch):
    monkeypatch.setattr(builder, "MAX_PROVENANCE_OBSERVATIONS", 2)
    proof = []
    with pytest.raises(ValueError, match="provenance_quota"):
        run(fixture(), provenance=proof)
    assert proof == []


def test_prepopulated_provenance_is_not_overwritten():
    proof = [{"preserved": True}]
    with pytest.raises(ValueError, match="input_quota"):
        run(fixture(), provenance=proof)
    assert proof == [{"preserved": True}]
