import unittest
from dataclasses import asdict

from motor_worker.policy import ActionChunk, GamepadState, KeyboardMouseState
from scripts.pilot.audit_motor_overlay import VARIANTS, overlay, summarize, window_steering


class OverlayAuditTests(unittest.TestCase):
    def test_source_and_repeat_control_are_byte_identical_and_no_source_mutation(self):
        source = bytes([90, 100, 110]) * (192 * 192)
        self.assertIs(overlay(source, 192, 'raw'), source)
        self.assertEqual(overlay(source, 192, 'raw_repeat'), source)
        self.assertNotEqual(overlay(source, 192, 'left'), source)
        self.assertEqual(source, bytes([90, 100, 110]) * (192 * 192))

    def test_probe_lines_share_origin_but_have_distinct_visible_targets(self):
        import numpy as np
        source = bytes(192 * 192 * 3)
        left, right = [np.frombuffer(overlay(source, 192, v), np.uint8).reshape(192, 192, 3)
                       for v in ('left', 'right')]
        self.assertTrue((left[180, 96] == right[180, 96]).all())
        self.assertGreater(int(left[93, 43].sum()), 0)
        self.assertEqual(int(right[93, 43].sum()), 0)
        self.assertFalse(left[:70].any())

    def test_invalid_variant_size_and_non_rgb_are_refused(self):
        for value in ((bytes(12), 192, 'left'), (bytes(12), 2, 'raw'),
                      (bytes(192 * 192 * 3), 192, 'route')):
            with self.subTest(value=value[1:]), self.assertRaises(ValueError):
                overlay(*value)

    def test_missing_or_duplicate_controls_cannot_create_a_positive_report(self):
        row = dict(image=0, seed=17, variant='raw', chunk={}, steering={'lateral': 0, 'camera': 0}, wallMs=10)
        for rows in ([], [row], [row, row]):
            with self.assertRaises(ValueError):
                summarize(rows)

    def test_random_raw_drift_is_visible_and_directional_change_is_not_navigation(self):
        rows = [dict(image=0, seed=17, variant=v, chunk=asdict(ActionChunk(
                     (KeyboardMouseState(('w',) if v == 'raw_repeat' else (), (), 0, 0),), 20)),
                     steering={'lateral': -1 if v == 'left' else 1 if v == 'right' else 0, 'camera': 0},
                     wallMs=25) for v in VARIANTS]
        result = summarize(rows)
        self.assertFalse(result['repeatRawIdentical'])
        self.assertEqual(result['positiveLateralPairs'], 1)
        self.assertFalse(result['directionalNavigationAccepted'])

    def test_window_weights_partial_last_state_and_ignores_later_predictions(self):
        negative = GamepadState((-1., 0.), (0., 0.), GamepadState.neutral().buttons)
        positive = GamepadState((1., 0.), (0., 0.), GamepadState.neutral().buttons)
        chunk = asdict(ActionChunk((negative, positive, negative), 10))
        result = window_steering(chunk, 150)
        self.assertAlmostEqual(result['meanOverCoveredInterval']['lateral'], -1 / 3)
        self.assertEqual(result['coveredMs'], 150)
        self.assertAlmostEqual(window_steering(chunk)['meanOverCoveredInterval']['lateral'], 0)

    def test_short_p2p_chunk_does_not_claim_200_ms_control_or_extend_hold(self):
        chunk = asdict(ActionChunk((KeyboardMouseState(('d',), (), 0, 0),), 20))
        result = window_steering(chunk)
        self.assertEqual(result['coveredMs'], 50)
        self.assertEqual(result['horizonMs'], 200)
        self.assertEqual(result['meanOverCoveredInterval']['lateral'], 1)
        self.assertEqual(result['tailPolicy'], 'UNSPECIFIED_NO_SYNTHETIC_HOLD')

    def test_invalid_horizon_and_state_values_are_refused(self):
        chunk = asdict(ActionChunk((GamepadState.neutral(),), 60))
        for horizon in (0, 2001, 1.5, True):
            with self.assertRaises(ValueError):
                window_steering(chunk, horizon)
        chunk['states'][0]['left'] = (99, 0)
        with self.assertRaises(ValueError):
            window_steering(chunk)
