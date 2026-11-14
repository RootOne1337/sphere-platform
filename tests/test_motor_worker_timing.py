"""Cadence must expose stalls that an average or short sample tail conceals."""

import math
import unittest

from motor_worker.protocol import ProtocolError
from motor_worker.timing import ResultTiming


class ResultTimingTests(unittest.TestCase):
    def test_no_observation_or_partial_window_cannot_pass_a_rate_requirement(self):
        timing = ResultTiming(5)
        timing.advance(50)
        self.assertFalse(timing.report()["measurementStarted"])
        timing.start(50)
        timing.accept(50.1, 50.0)
        timing.close(50.5)
        report = timing.report()
        self.assertIsNone(report["allCompleteWindowsMeetRequestedCount"])
        self.assertEqual(report["receiverAgeAtResultMaxMs"], 100)
        self.assertEqual(report["maximumSilenceIncludingLeadingTrailingMs"], 400)

    def test_average_five_can_hide_a_complete_second_without_any_results(self):
        timing = ResultTiming(5)
        timing.start(0)
        for n in range(10):
            timing.accept(n * 0.05, n * 0.05)
        timing.close(2)
        report = timing.report()
        self.assertEqual(report["averageAcceptedHz"], 5)
        self.assertEqual(report["completeOneSecondWindows"], 2)
        self.assertEqual(report["minimumAcceptedInCompleteWindow"], 0)
        self.assertFalse(report["allCompleteWindowsMeetRequestedCount"])
        self.assertEqual(report["maximumSilenceIncludingLeadingTrailingMs"], 1550)

    def test_boundary_result_belongs_to_next_window_and_trailing_window_counts(self):
        timing = ResultTiming(2)
        timing.start(10)
        for at in (10.1, 10.6, 11.0, 11.5):
            timing.accept(at, at - 0.1)
        timing.close(12)
        report = timing.report()
        self.assertEqual(report["minimumAcceptedInCompleteWindow"], 2)
        self.assertTrue(report["allCompleteWindowsMeetRequestedCount"])
        self.assertEqual(report["gapP95Ms"], 500)

    def test_long_silence_includes_empty_windows_without_allocating_per_window(self):
        timing = ResultTiming(5)
        timing.start(100)
        timing.close(100100)
        report = timing.report()
        self.assertEqual(report["completeOneSecondWindows"], 100000)
        self.assertEqual(report["minimumAcceptedInCompleteWindow"], 0)
        self.assertEqual(report["maximumSilenceIncludingLeadingTrailingMs"], 100000000)
        self.assertIsNone(report["receiverAgeAtResultP95Ms"])

    def test_history_is_bounded_but_maxima_survive_eviction(self):
        timing = ResultTiming()
        timing.start(0)
        timing.accept(1, 0)
        for n in range(1, 1001):
            timing.accept(1 + n / 10, 1 + n / 10)
        timing.close(101)
        report = timing.report()
        self.assertEqual(report["acceptedResults"], 1001)
        self.assertEqual(report["ageTailSamples"], 128)
        self.assertEqual(report["gapTailSamples"], 128)
        self.assertEqual(report["receiverAgeAtResultMaxMs"], 1000)
        self.assertEqual(report["receiverAgeAtResultP95Ms"], 0)
        self.assertEqual(report["maximumSilenceIncludingLeadingTrailingMs"], 1000)

    def test_close_freezes_counts_and_does_not_add_post_cleanup_silence(self):
        timing = ResultTiming(2.5)
        timing.start(0)
        timing.accept(0.1, 0)
        timing.close(1)
        before = timing.report()
        timing.advance(100)
        timing.start(100)
        timing.close(100)
        self.assertEqual(timing.report(), before)
        self.assertEqual(before["requiredCountPerCompleteWindow"], 3)
        with self.assertRaises(ProtocolError):
            timing.accept(100, 99)

    def test_invalid_rate_and_sample_do_not_silently_enter_statistics(self):
        for rate in (0, -1, 121, True, math.nan, math.inf, "5", 10**1000):
            with self.subTest(rate=rate), self.assertRaises(ProtocolError):
                ResultTiming(rate)
        timing = ResultTiming(5)
        for at in (True, -1, math.nan, math.inf, 10**1000):
            with self.subTest(at=at), self.assertRaises(ProtocolError):
                timing.start(at)
        timing.start(10)
        with self.assertRaises(ProtocolError):
            timing.accept(10, 11)
        timing.advance(9)
        self.assertEqual(timing.report()["clockReversalsIgnored"], 1)
        timing.accept(9, 8)
        self.assertEqual(timing.report()["clockReversalsIgnored"], 2)
        self.assertEqual(timing.report()["acceptedResults"], 0)
