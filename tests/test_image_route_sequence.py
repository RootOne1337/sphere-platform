"""Temporal image-reference evidence tests; none establish spatial ground truth."""

import hashlib
import math
import random
import unittest
from dataclasses import FrozenInstanceError

from motor_worker.image_route_sequence import CausalSequenceBeam, RouteSequenceFilter


def sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


class ImageRouteSequenceTests(unittest.TestCase):
    def setUp(self):
        self.times = (0.0, 0.2, 0.45, 2.0, 2.15, 2.8, 5.0, 5.1)
        self.sequence = RouteSequenceFilter(self.times)
        self.serial = 0

    def scores(self, index, strength=0.9, **others):
        scores = [0.0] * len(self.times)
        scores[index] = strength
        for other, value in others.items():
            scores[int(other)] = value
        return scores

    def update(
        self,
        scores,
        *,
        at=None,
        sequence=None,
        source=None,
        received=None,
        now=None,
        checked=None,
        target=None,
    ):
        self.serial += 1
        sequence = self.serial if sequence is None else sequence
        at = self.serial * 0.1 if at is None else at
        return (target or self.sequence).update(
            scores,
            source_sequence=sequence,
            received_at=at if received is None else received,
            now=at if now is None else now,
            source_sha256=sha(self.serial if source is None else source),
            checked=checked,
        )

    def acquire(self, index, start=0.1):
        return [self.update(self.scores(index), at=start + i * 0.1) for i in range(3)]

    def test_middle_start_needs_three_distinct_query_sources(self):
        results = self.acquire(4)
        self.assertEqual([r.status for r in results], ["unknown", "unknown", "reference_selected"])
        self.assertEqual([r.confirmations for r in results], [1, 2, 3])
        result = results[-1]
        self.assertEqual((result.index, result.source_seconds), (4, 2.15))
        self.assertEqual(result.confirmation_sources, (sha(1), sha(2), sha(3)))
        self.assertFalse(result.position_confirmed)
        self.assertFalse(result.execution_qualified)
        with self.assertRaises(FrozenInstanceError):
            result.execution_qualified = True

    def test_last_reference_has_no_arrival_semantics(self):
        result = self.acquire(7)[-1]
        self.assertEqual(result.status, "reference_selected")
        self.assertEqual(result.reason, "image_reference_not_pose_or_arrival")
        self.assertFalse(hasattr(result, "arrived"))

    def test_repeated_facades_never_acquire_at_startup(self):
        for _ in range(6):
            result = self.update(self.scores(1, **{"6": 0.78}))
            self.assertEqual(
                (result.status, result.index, result.confirmations), ("ambiguous", None, 0)
            )
            self.assertEqual(result.candidate_indices, (1, 6))
            self.assertAlmostEqual(result.confidence_gap, 0.12)

    def test_adjacent_reference_peaks_are_one_image_neighborhood(self):
        scores = self.scores(1, **{"0": 0.89, "2": 0.88})
        result = [self.update(scores) for _ in range(3)][-1]
        self.assertEqual(
            (result.status, result.index, result.candidate_indices), ("reference_selected", 1, (1,))
        )

    def test_long_plateau_is_not_transitively_merged(self):
        sequence = RouteSequenceFilter((0.0, 0.5, 1.0, 1.5, 2.0))
        result = self.update([0.8] * 5, target=sequence)
        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.candidate_indices, (0, 2, 4))

    def test_decimal_boundaries_do_not_create_aliases_or_break_confirmations(self):
        sequence = RouteSequenceFilter((2.0, 2.6, 4.0))
        results = [self.update([0.9, 0.89, 0.0], at=at, target=sequence) for at in (0.1, 0.6, 1.1)]
        self.assertEqual([r.confirmations for r in results], [1, 2, 3])
        self.assertEqual(
            (results[-1].status, results[-1].candidate_indices), ("reference_selected", (0,))
        )

    def test_relative_and_absolute_thresholds_are_both_required(self):
        result = self.update(self.scores(1, 0.34))
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.confirmations, 0)
        result = self.update(self.scores(1, 0.4, **{"6": 0.34}))
        self.assertEqual(result.candidate_indices, (1,))
        result = self.update(self.scores(1, 0.8, **{"6": 0.6}))
        self.assertEqual(result.status, "ambiguous")  # equality at .75 counts

    def test_unchecked_scores_cannot_win_or_form_a_confidence_gap(self):
        scores = self.scores(1, 0.8, **{"6": 1.0})
        checked = [False] * len(scores)
        checked[1] = True
        result = [self.update(scores, checked=checked) for _ in range(3)][-1]
        self.assertEqual((result.status, result.index), ("reference_selected", 1))
        self.assertEqual(result.checked_references, 1)
        self.assertIsNone(result.confidence_gap)
        unchecked = self.update(scores, checked=[False] * len(scores))
        self.assertEqual(
            (unchecked.status, unchecked.reason, unchecked.confirmations),
            ("unknown", "no_checked_reference", 0),
        )

    def test_prior_only_orders_aliases_and_cannot_export_an_index(self):
        self.acquire(1)
        result = self.update(self.scores(6, **{"1": 0.8}), at=0.4)
        self.assertEqual((result.status, result.index), ("ambiguous", None))
        self.assertEqual(result.candidate_indices, (1, 6))  # .8 is geometrically competitive
        self.assertEqual(result.confirmations, 0)
        # Ambiguity never renews the prior. After expiry use geometry order.
        result = self.update(self.scores(6, **{"1": 0.8}), at=0.9)
        self.assertEqual(result.candidate_indices, (6, 1))

    def test_a_weak_match_near_prior_does_not_override_stronger_new_place(self):
        self.acquire(1)
        scores = self.scores(6, **{"1": 0.4})
        results = [self.update(scores, at=0.4 + i * 0.1) for i in range(3)]
        self.assertEqual([r.confirmations for r in results], [1, 2, 3])
        self.assertEqual((results[-1].status, results[-1].index), ("reference_selected", 6))

    def test_loss_clears_confirmation_and_does_not_auto_advance(self):
        self.acquire(1)
        lost = self.update([0.0] * len(self.times))
        self.assertEqual((lost.status, lost.index, lost.source_seconds), ("unknown", None, None))
        self.assertEqual(lost.confirmations, 0)
        self.assertEqual(self.update(self.scores(1)).confirmations, 1)

    def test_ambiguity_requires_three_new_unique_sources_to_reacquire(self):
        self.acquire(1)
        self.update(self.scores(1, **{"6": 0.8}))
        results = [self.update(self.scores(1)) for _ in range(3)]
        self.assertEqual([r.status for r in results], ["unknown", "unknown", "reference_selected"])

    def test_repeated_sha_even_after_other_frames_does_not_confirm_or_move_prior(self):
        self.update(self.scores(1), source="a", at=0.1)
        self.update(self.scores(1), source="b", at=0.2)
        stale = self.update(self.scores(6), source="a", at=0.3)
        self.assertEqual((stale.status, stale.index, stale.confirmations), ("stale", None, 0))
        result = self.update(self.scores(1), source="c", at=0.4)
        self.assertEqual(result.confirmation_sources, (sha("a"), sha("b"), sha("c")))
        self.assertEqual(result.index, 1)

    def test_nonincreasing_sequence_is_consumed_without_geometric_update(self):
        self.update(self.scores(1), sequence=10, at=0.1)
        stale = self.update(self.scores(6), sequence=9, at=0.2, source="late")
        self.assertEqual(stale.status, "stale")
        # A rejected image cannot be relabelled with a newer delivery ID.
        self.assertEqual(
            self.update(self.scores(6), sequence=11, at=0.3, source="late").status, "stale"
        )
        self.assertEqual(self.update(self.scores(1), sequence=12, at=0.4).confirmations, 2)

    def test_old_receipt_and_clock_rollback_cannot_add_confirmation(self):
        self.update(self.scores(1), at=1.0)
        result = self.update(self.scores(6), received=0.9, now=1.1)
        self.assertEqual(result.status, "stale")
        result = self.update(self.scores(6), received=1.05, now=1.05)
        self.assertEqual(result.status, "stale")
        self.assertEqual(self.update(self.scores(1), at=1.2).confirmations, 2)

    def test_expired_and_future_frames_cannot_be_relabelled_as_fresh(self):
        expired = self.update(self.scores(1), source="expired", received=0.1, now=0.36)
        self.assertEqual(expired.reason, "source_outside_freshness_window")
        self.assertEqual(self.update(self.scores(1), source="expired", at=0.4).status, "stale")
        future = self.update(self.scores(1), source="future", received=100.0, now=0.5)
        self.assertEqual(future.status, "stale")
        # A malformed future receipt cannot permanently poison the receipt clock.
        self.assertEqual(self.update(self.scores(1), at=0.6).confirmations, 1)

    def test_freshness_default_boundary_and_explicit_virtual_clock(self):
        result = self.update(self.scores(1), received=0.0, now=0.25)
        self.assertEqual(result.confirmations, 1)
        sequence = RouteSequenceFilter(self.times, max_frame_age=2.0)
        result = self.update(self.scores(1), received=1.0, now=2.5, target=sequence)
        self.assertEqual(result.confirmations, 1)

    def test_gap_restarts_acquisition_using_current_strong_frame(self):
        self.acquire(1)
        result = self.update(self.scores(1), at=1.0)
        self.assertEqual((result.status, result.confirmations), ("unknown", 1))
        self.assertEqual(self.update(self.scores(1), at=1.1).confirmations, 2)

    def test_reverse_and_uneven_speed_use_reference_pts_not_index_distance(self):
        sequence = RouteSequenceFilter((0.0, 0.01, 0.02, 0.03, 0.4, 1.1, 2.0, 2.5))
        # Reverse then slower motion, then faster forward: no monotonic rule.
        for at, index in ((0.1, 7), (0.2, 6), (0.4, 5), (0.5, 5), (0.7, 6)):
            scores = [0.0] * 8
            scores[index] = 0.9
            result = self.update(scores, at=at, target=sequence)
        self.assertEqual((result.status, result.index), ("reference_selected", 6))
        dense = RouteSequenceFilter(tuple(i * 0.001 for i in range(256)))
        results = []
        for i in (0, 128, 255):
            scores = [0.0] * 256
            scores[i] = 0.9
            results.append(self.update(scores, at=1.0 + len(results) * 0.1, target=dense))
        self.assertEqual(results[-1].index, 255)

    def test_large_reference_jump_restarts_even_with_adjacent_indices(self):
        sequence = RouteSequenceFilter((0.0, 10.0))
        self.update([0.9, 0.0], at=0.1, target=sequence)
        self.update([0.9, 0.0], at=0.2, target=sequence)
        result = self.update([0.0, 0.9], at=0.3, target=sequence)
        self.assertEqual((result.status, result.confirmations), ("unknown", 1))

    def test_history_capacity_fails_closed_without_replay_eviction(self):
        sequence = RouteSequenceFilter(self.times, max_seen_sources=3)
        for _ in range(3):
            result = self.update(self.scores(1), target=sequence)
        self.assertEqual(result.status, "reference_selected")
        result = self.update(self.scores(1), target=sequence)
        self.assertEqual(
            (result.status, result.index, result.reason),
            ("unknown", None, "source_history_capacity"),
        )
        result = self.update(self.scores(1), source=1, target=sequence)
        self.assertEqual(result.status, "stale")

    def test_invalid_observations_raise_and_break_confirmation(self):
        invalid = (
            {"scores": [0.8]},
            {"scores": [math.nan] * 8},
            {"scores": [math.inf] * 8},
            {"scores": [1.01] * 8},
            {"scores": [True] * 8},
            {"checked": [True]},
            {"checked": [1] * 8},
            {"source_sequence": True},
            {"received_at": -1.0},
            {"now": math.nan},
            {"source_sha256": "x" * 64},
        )
        for changes in invalid:
            with self.subTest(changes=changes):
                sequence = RouteSequenceFilter(self.times)
                self.update(self.scores(1), at=0.1, target=sequence)
                args = dict(
                    scores=self.scores(1),
                    source_sequence=100,
                    received_at=0.2,
                    source_sha256=sha("invalid"),
                    now=0.2,
                )
                args.update(changes)
                with self.assertRaises(ValueError):
                    sequence.update(**args)
                self.assertEqual(
                    self.update(self.scores(1), at=0.3, target=sequence).confirmations, 1
                )

    def test_invalid_options(self):
        for times in (
            (),
            (0.0,),
            [0.0, 1.0],
            (0.0, 0.0),
            (1.0, 0.0),
            (-1.0, 0.0),
            (0.0, math.inf),
            (False, 1.0),
            tuple(range(257)),
        ):
            with self.subTest(times=times), self.assertRaises(ValueError):
                RouteSequenceFilter(times)
        for key, value in (
            ("min_score", 0),
            ("relative_peak", 1.1),
            ("peak_radius_seconds", 0),
            ("max_frame_age", math.nan),
            ("max_observation_gap", -1),
            ("max_reference_speed", True),
            ("reference_slack_seconds", -1),
            ("max_seen_sources", 2),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                RouteSequenceFilter(self.times, **{key: value})


class CausalSequenceBeamTests(unittest.TestCase):
    def setUp(self):
        self.times = tuple(float(i) for i in range(10))
        self.beam = CausalSequenceBeam(self.times)
        self.serial = 0

    def observe(
        self,
        index=None,
        *,
        values=None,
        at=None,
        checked=None,
        source=None,
        sequence=None,
        received=None,
        now=None,
        beam=None,
    ):
        self.serial += 1
        beam = beam or self.beam
        if values is None:
            values = [0.0] * len(beam.reference_seconds)
            if index is not None:
                values[index] = 0.9
        at = self.serial * 0.1 if at is None else at
        return beam.update(
            values,
            checked=checked,
            source_sequence=self.serial if sequence is None else sequence,
            source_sha256=sha(self.serial if source is None else source),
            received_at=at if received is None else received,
            now=at if now is None else now,
        )

    def test_acquires_moving_path_not_repeated_winner_index(self):
        results = [self.observe(i) for i in (3, 4, 5)]
        self.assertEqual([r.status for r in results], ["unknown", "unknown", "reference_selected"])
        result = results[-1]
        self.assertEqual((result.index, result.source_seconds), (5, 5.0))
        self.assertEqual(result.support_lineage_indices, (3, 4, 5))
        self.assertEqual(result.confirmation_sources, (sha(1), sha(2), sha(3)))

    def test_middle_start_and_reverse_work_without_start_or_direction_prior(self):
        results = [self.observe(i) for i in (7, 6, 5, 4)]
        self.assertEqual((results[2].status, results[2].index), ("reference_selected", 5))
        self.assertEqual(results[-1].support_lineage_indices, (7, 6, 5, 4))

    def test_uneven_reference_timestamps_and_variable_rate(self):
        beam = CausalSequenceBeam((0.0, 0.01, 0.03, 0.5, 1.3, 2.0))
        results = [
            self.observe(i, at=t, beam=beam)
            for i, t in ((1, 0.1), (3, 0.2), (4, 0.4), (5, 0.5), (4, 0.7))
        ]
        self.assertEqual(results[-1].status, "reference_selected")
        self.assertEqual(results[-1].support_lineage_indices, (1, 3, 4, 5, 4))

    def test_two_equally_supported_facades_remain_ambiguous(self):
        values = [0.0] * 10
        values[1] = values[8] = 0.9
        for _ in range(20):
            result = self.observe(values=values)
            self.assertEqual((result.status, result.index), ("ambiguous", None))
            self.assertEqual(result.candidate_indices, (1, 8))
            self.assertAlmostEqual(result.uncalibrated_log_margin, 0.0)

    def test_one_far_facade_impulse_cannot_teleport_confirmed_path(self):
        for _ in range(4):
            self.observe(1)
        values = [0.0] * 10
        values[8] = 1.0
        result = self.observe(values=values)
        self.assertIsNone(result.index)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.confirmations, 0)
        self.assertEqual(result.reason, "best_path_has_no_current_checked_support")

    def test_all_unknown_cannot_continue_prediction_and_breaks_path_proof(self):
        for _ in range(3):
            self.observe(3)
        result = self.observe()
        self.assertEqual((result.status, result.index, result.confirmations), ("unknown", None, 0))
        self.assertEqual(self.observe(3).confirmations, 1)
        self.assertEqual(self.observe(3).status, "unknown")
        self.assertEqual(self.observe(3).status, "reference_selected")

    def test_unchecked_nodes_are_neutral_but_never_confirm_a_path(self):
        self.observe(3)
        self.observe(3)
        before = tuple(self.beam._log_states)
        result = self.observe(3, checked=[False] * 10)
        self.assertIsNone(result.index)
        self.assertEqual(result.checked_fraction, 0.0)
        self.assertEqual(result.confirmations, 0)
        # Neutral values can propagate to reachable states, without a negative
        # emission or a fabricated checked observation at their destination.
        self.assertEqual(max(before), max(self.beam._log_states))
        self.assertEqual(self.observe(3).confirmations, 1)
        self.assertEqual(self.observe(3).confirmations, 2)
        self.assertEqual(self.observe(3).status, "reference_selected")

    def test_unchecked_best_state_cannot_export_checked_runner_as_location(self):
        for _ in range(4):
            self.observe(2)
        checked = [False] * 10
        checked[8] = True
        result = self.observe(8, checked=checked)
        self.assertEqual((result.status, result.index, result.confirmations), ("unknown", None, 0))

    def test_gap_resets_wrong_prior_and_reacquires_from_fresh_geometry(self):
        for _ in range(4):
            self.observe(1)
        results = [self.observe(8, at=t) for t in (2.0, 2.1, 2.2)]
        self.assertEqual([r.confirmations for r in results], [1, 2, 3])
        self.assertEqual((results[-1].status, results[-1].index), ("reference_selected", 8))
        self.assertEqual(results[-1].confirmation_sources, (sha(5), sha(6), sha(7)))

    def test_duplicate_sha_and_stale_sequence_do_not_update_dp(self):
        self.observe(3, source="a", sequence=1)
        snapshot = tuple(self.beam._log_states)
        for kwargs in ({"source": "a", "sequence": 2}, {"source": "b", "sequence": 1}):
            result = self.observe(8, **kwargs)
            self.assertEqual((result.status, result.index), ("stale", None))
            self.assertEqual(tuple(self.beam._log_states), snapshot)
        self.assertEqual(self.observe(3, source="c", sequence=4).confirmations, 2)
        self.assertEqual(self.observe(3, source="d", sequence=5).status, "reference_selected")

    def test_expired_receipt_and_clock_rollback_do_not_move_path(self):
        self.observe(3, at=1.0)
        snapshot = tuple(self.beam._log_states)
        for kwargs in (
            {"received": 1.05, "now": 1.4},
            {"received": 1.1, "now": 1.2},
            {"received": 1.0, "now": 1.4},
        ):
            result = self.observe(8, **kwargs)
            self.assertEqual(result.status, "stale")
            self.assertEqual(tuple(self.beam._log_states), snapshot)
        self.assertEqual(self.observe(3, at=1.5).confirmations, 2)

    def test_invalid_observation_breaks_path_confirmation(self):
        self.observe(3)
        self.observe(3)
        with self.assertRaises(ValueError):
            self.observe(values=[math.nan] * 10)
        self.assertEqual(self.observe(3).confirmations, 1)

    def test_zero_evidence_is_unknown_with_uniform_uncalibrated_mass(self):
        for _ in range(5):
            result = self.observe()
            self.assertEqual(
                (result.status, result.index, result.confirmations), ("unknown", None, 0)
            )
            self.assertAlmostEqual(sum(result.uncalibrated_posterior), 1.0)
            self.assertEqual(len(set(result.uncalibrated_posterior)), 1)

    def test_gap_is_absent_without_a_checked_separated_runner(self):
        checked = [False] * 10
        checked[3] = True
        for _ in range(3):
            result = self.observe(3, checked=checked)
        self.assertIsNone(result.confidence_gap)
        self.assertIsNone(result.uncalibrated_confidence)
        self.assertIsNotNone(result.uncalibrated_log_margin)
        self.assertEqual(result.checked_indices, (3,))
        self.assertAlmostEqual(result.checked_fraction, 0.1)
        self.assertFalse(result.confidence_is_calibrated)
        self.assertFalse(result.position_confirmed)
        self.assertFalse(result.execution_qualified)

    def test_history_is_bounded_and_lineage_preserves_moving_indices(self):
        beam = CausalSequenceBeam(tuple(float(i) for i in range(64)))
        for index in range(60):
            result = self.observe(index, beam=beam)
        self.assertEqual(
            (result.status, result.index, result.confirmations), ("reference_selected", 59, 32)
        )
        self.assertEqual(result.support_lineage_indices, tuple(range(28, 60)))
        self.assertEqual(result.confirmation_sources, tuple(sha(i) for i in range(29, 61)))
        self.assertEqual(len(beam._ancestry), 32)
        self.assertLessEqual(
            sum(parents.itemsize * len(parents) for parents, _ in beam._ancestry), 4096
        )

    def test_linear_window_maxima_match_exhaustive_allowed_predecessors(self):
        rng = random.Random(7)
        times = tuple(sorted(rng.sample(range(30000), 256)))
        beam = CausalSequenceBeam(times)
        beam._log_states = [float(rng.randrange(-30, 1)) for _ in times]
        for limit in (0.0, 0.6, 100.0, 9000.0):
            expected = [
                max(
                    (j for j, other in enumerate(times) if abs(other - t) <= limit),
                    key=lambda j: beam._log_states[j],
                )
                for t in times
            ]
            self.assertEqual(list(beam._predecessors(limit)), expected)

    def test_invalid_beam_options(self):
        for key, value in (
            ("log_margin", -0.1),
            ("log_margin", math.nan),
            ("emission_scale", 0),
            ("emission_scale", math.inf),
            ("weak_emission", 0),
            ("weak_emission", True),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                CausalSequenceBeam(self.times, **{key: value})


if __name__ == "__main__":
    unittest.main()
