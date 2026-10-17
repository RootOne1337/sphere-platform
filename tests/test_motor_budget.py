"""Arithmetic/admission boundaries; no GPU, model, emulator or network access."""

import json
import unittest

from scripts.pilot.motor_budget import plan_budget


class MotorBudgetTests(unittest.TestCase):
    def test_fifty_at_five_requires_250_real_observations(self):
        result = plan_budget(50, 5, source_fps=60, video_mbps=1)
        self.assertEqual(result["aggregateObservationsPerSecond"], 250)
        self.assertEqual(result["aggregateDecodeFramesPerSecondIfEverySourceFrameDecoded"], 3000)
        self.assertEqual(result["aggregateVideoPayloadMbps"], 50)
        self.assertAlmostEqual(result["rawRgb256ObservationPayloadMbps"], 393.216)
        self.assertAlmostEqual(result["maximumBatchMsForThisRoundBudget"], 2.8)
        self.assertIsNone(result["inferenceArithmeticFitsBudget"])
        self.assertFalse(result["gameplayReady"])

    def test_final_partial_batch_is_not_free_capacity(self):
        result = plan_budget(50, 5, batch_size=8, batch_ms=22.4)
        self.assertEqual(result["batchesPerSynchronizedRound"], 7)
        self.assertAlmostEqual(result["roundServiceMsAtSuppliedCost"], 156.8)
        self.assertEqual(result["maximumBatchMsForThisRoundBudget"], 20)
        self.assertFalse(result["inferenceArithmeticFitsBudget"])

    def test_budget_boundary_does_not_certify_gameplay(self):
        result = plan_budget(50, 5, batch_size=8, batch_ms=20)
        self.assertTrue(result["inferenceArithmeticFitsBudget"])
        self.assertFalse(result["gameplayReady"])
        self.assertAlmostEqual(result["roundDutyAtSuppliedCost"], 0.7)
        self.assertEqual(result["kind"], "CALCULATION_NOT_A_BENCHMARK")

    def test_input_sampling_and_decode_rates_are_independent(self):
        slow = plan_budget(50, 4, source_fps=60)
        fast = plan_budget(50, 5, source_fps=60)
        self.assertEqual(slow["aggregateObservationsPerSecond"], 200)
        self.assertEqual(
            slow["aggregateDecodeFramesPerSecondIfEverySourceFrameDecoded"],
            fast["aggregateDecodeFramesPerSecondIfEverySourceFrameDecoded"],
        )
        self.assertIsNone(slow["aggregateVideoPayloadMbps"])

    def test_finite_json_output_and_no_implicit_measurements(self):
        result = plan_budget(1, 0.5)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result["observationPeriodMs"], 2000)
        self.assertIsNone(result["roundServiceMsAtSuppliedCost"])
        self.assertIsNone(result["aggregateDecodeFramesPerSecondIfEverySourceFrameDecoded"])

    def test_fast_inference_does_not_make_slow_video_fresh(self):
        result = plan_budget(1, 5, source_fps=1, batch_ms=1)
        self.assertTrue(result["inferenceArithmeticFitsBudget"])
        self.assertFalse(result["sourceRateMeetsRequestedObservationRate"])
        self.assertFalse(result["gameplayReady"])

    def test_reject_invalid_counts_and_fake_batch_capacity(self):
        for count in [0, -1, True, 1.5, 10001]:
            with self.subTest(count=count), self.assertRaises(ValueError):
                plan_budget(count, 5)
        for size in [0, True, 1.5, 51]:
            with self.subTest(size=size), self.assertRaises(ValueError):
                plan_budget(50, 5, batch_size=size)

    def test_reject_invalid_numeric_budgets(self):
        for value in [0, -1, True, float("nan"), float("inf")]:
            for name in ["observation_hz", "batch_ms", "source_fps", "video_mbps"]:
                values = {"devices": 50, "observation_hz": 5, name: value}
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    plan_budget(**values)
        for value in [0, 1, -1, True, float("nan"), float("inf")]:
            with self.subTest(utilization=value), self.assertRaises(ValueError):
                plan_budget(50, 5, utilization=value)

    def test_reject_overflow_in_derived_values(self):
        for values in [
            {"observation_hz": 1e308},
            {"observation_hz": 1e-320},
            {"observation_hz": 5, "batch_ms": 1e308},
            {"observation_hz": 5, "source_fps": 1e308},
        ]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                plan_budget(devices=50, **values)


if __name__ == "__main__":
    unittest.main()
