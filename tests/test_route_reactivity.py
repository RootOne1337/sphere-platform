import unittest

from scripts.pilot.route_reactivity import summarize_reactivity


class ReactivityTests(unittest.TestCase):
    def sample(self, at, **overrides):
        return dict(elapsedMs=at, ageMs=40, computeMs=20, state='following', poseState='localized') | overrides

    def event(self, stage, at, **overrides):
        return dict(stage=stage, at_ms=at, sequence=8, gesture=2, action=2, pointer_id=0) | overrides

    def test_receipt_pairs_only_native_identity_not_source_sequence_or_device_clock(self):
        report = dict(observations=[self.sample(200)], nativeInputs=[
            self.event('submitted', 900), self.event('receipt', 927, outcome='applied', device_uptime_ms=1)])
        result = summarize_reactivity(report)
        self.assertEqual(result['nativeSubmitToAppliedAckMs']['p95'], 27)
        self.assertFalse(result['fullAndroidLatencyKnown'])
        self.assertFalse(result['executionQualified'])

    def test_duplicate_or_missing_submissions_never_create_false_fast_ack(self):
        rows = [self.event('submitted', 900), self.event('submitted', 910),
                self.event('receipt', 927, outcome='applied'),
                self.event('receipt', 940, sequence=9, outcome='applied')]
        result = summarize_reactivity(dict(nativeInputs=rows))
        self.assertEqual(result['nativeSubmitToAppliedAckMs']['count'], 0)
        self.assertEqual(result['nativeReceiptsAmbiguous'], 1)
        self.assertEqual(result['nativeReceiptsUnmatched'], 1)

    def test_tail_or_decimated_coverage_does_not_claim_original_rate(self):
        report = dict(observationCount=200, observations=[self.sample(1000), self.sample(1600)])
        result = summarize_reactivity(report)
        self.assertEqual(result['observationCoverage'], 'incomplete')
        self.assertEqual(result['retainedCorrectionGapMs']['maximum'], 600)
        self.assertFalse(result['correctionCadenceQualified'])

    def test_stale_unknown_waiting_are_not_usable_corrections(self):
        rows = [self.sample(100), {**self.sample(200), 'poseState': 'unknown'},
                {**self.sample(300), 'ageMs': 250}, {**self.sample(400), 'state': 'waiting'}, self.sample(500)]
        result = summarize_reactivity(dict(observationCount=5, observations=rows))
        self.assertEqual(result['freshFollowingCorrections'], 2)
        self.assertEqual(result['retainedCorrectionGapMs']['p95'], 400)
        self.assertEqual(result['sourceFrameToReplyMs']['maximum'], 250)

    def test_missing_counters_are_unknown_and_empty_intervals_are_null(self):
        result = summarize_reactivity({})
        self.assertEqual(result['observationCoverage'], 'unknown')
        self.assertIsNone(result['nativeSubmitToAppliedAckMs']['maximum'])

    def test_negative_nan_or_reordered_clock_rejected(self):
        for rows in ([self.sample(200), self.sample(100)], [{**self.sample(100), 'computeMs': float('nan')}],
                     [{**self.sample(100), 'ageMs': -1}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                summarize_reactivity(dict(observations=rows))

    def test_rejected_input_never_counts_as_applied(self):
        result = summarize_reactivity(dict(nativeInputs=[self.event('submitted', 900),
            self.event('receipt', 940, outcome='expired')]))
        self.assertEqual(result['nativeSubmitToAppliedAckMs']['count'], 0)
        self.assertEqual(result['nativeRejectedOutcomes'], {'expired': 1})
