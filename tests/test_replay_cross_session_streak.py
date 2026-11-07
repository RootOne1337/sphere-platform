import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.replay_cross_session_streak import run


class ReplayStreakTests(unittest.TestCase):
    def test_replay_keeps_decisions_and_counts_repeated_endpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.json"
            prior = root / "prior.json"
            prior.write_text(
                json.dumps({"source_sha256": "a" * 64, "reference_times": [0.0, 0.5, 1.0]})
            )
            samples = []
            for i, idx in enumerate([0, 1, 1, 2, 2, 2]):
                samples.append(
                    dict(
                        frame=i + 1,
                        seconds=(i + 1) * 0.2,
                        candidates=[idx],
                        state="confirming" if i < 3 else "hypothesis",
                        reference=None if i < 3 else 2,
                    )
                )
            source.write_text(
                json.dumps(
                    dict(
                        distinct_recordings=True,
                        physical_actions=0,
                        source_sha256={"reference": "a" * 64},
                        results={"ranked": {"samples": samples}},
                    )
                )
            )
            result = run(source, prior, root / "out")
            self.assertEqual(result["results"]["ranked"]["max_reference_streak"], 3)
            self.assertEqual(result["results"]["ranked"]["tail_hypothesis_frames"], 3)
            self.assertFalse(result["execution_qualified"])

    def test_replay_refuses_changed_saved_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.json"
            prior = root / "prior.json"
            prior.write_text(
                json.dumps({"source_sha256": "a" * 64, "reference_times": [0.0, 0.5, 1.0]})
            )
            source.write_text(
                json.dumps(
                    dict(
                        distinct_recordings=True,
                        physical_actions=0,
                        source_sha256={"reference": "a" * 64},
                        results={
                            "ranked": {
                                "samples": [
                                    dict(
                                        frame=1,
                                        seconds=0.2,
                                        candidates=[0],
                                        state="hypothesis",
                                        reference=0,
                                    )
                                ]
                            }
                        },
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "replay_diverged"):
                run(source, prior, root / "out")
