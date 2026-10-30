import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.pilot.compare_route_tracking import checkpoint, compare, summarize


@unittest.skipUnless(importlib.util.find_spec("numpy"), "optional CPU vision dependencies required")
class TrackingComparisonTests(unittest.TestCase):
    @staticmethod
    def report(states, offset=0.):
        return dict(capture_manifest_sha256="a"*64, reference_indices_excluded=89,
            counts={s: states.count(s) for s in set(states)}, compute_ms={"p50": 10.},
            samples=[dict(source_index=i+1, media_seconds=i*.2,
                tracking={"method": "map_anchored_flow"},
                pose=dict(state=state, center=[offset, 0., i], rotation=[1., 0., 0., 0., 1., 0., 0., 0., 1.]))
                     for i, state in enumerate(states)])

    def test_agreement_and_asymmetric_losses_do_not_claim_world_accuracy(self):
        route = SimpleNamespace(camera_trace=((0., 0., 0.), (0., 0., 2.)))
        result = summarize(self.report(["localized", "localized", "unknown"]),
                           self.report(["localized", "unknown", "localized"], offset=.2), route)
        self.assertEqual(result["baseline_localized_but_tracking_not"], 1)
        self.assertEqual(result["tracking_localized_but_baseline_not"], 1)
        self.assertAlmostEqual(result["center_agreement_reference_steps"]["maximum"], .1)
        self.assertFalse(result["metric_accuracy_known"])
        self.assertFalse(result["default_localizer_changed"])
        self.assertFalse(result["navigation_qualified"])

    def test_different_queries_or_media_timestamps_are_rejected(self):
        for field, value in (("source_index", 42), ("media_seconds", 8.)):
            first, second = self.report(["unknown"]), self.report(["unknown"])
            second["samples"][0][field] = value
            with self.assertRaisesRegex(ValueError, "different_queries"):
                summarize(first, second, object())
        first, second = self.report(["unknown"]), self.report(["unknown"])
        second["capture_manifest_sha256"] = "b"*64
        with self.assertRaisesRegex(ValueError, "different_queries"):
            summarize(first, second, object())

    def test_guard_refuses_before_loading_capture_or_creating_comparison(self):
        with TemporaryDirectory() as folder:
            output = Path(folder)/"new-result"
            with patch("scripts.pilot.compare_route_tracking.collect", return_value={}), \
                 patch("scripts.pilot.compare_route_tracking.evaluate", return_value=["ram_headroom_low"]) as evaluate:
                with self.assertRaisesRegex(RuntimeError, "resource_guard"):
                    compare("not-opened", "not-loaded", "a"*64, output)
                self.assertEqual(evaluate.call_args.kwargs["min_ram_gib"], 12)
            self.assertFalse(output.exists())
            (Path(folder)/"CANCEL").touch()
            with patch("scripts.pilot.compare_route_tracking.collect") as collect:
                with self.assertRaisesRegex(RuntimeError, "cancelled"):
                    checkpoint(Path(folder))
                collect.assert_not_called()
