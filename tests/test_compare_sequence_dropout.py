import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.compare_sequence_dropout import run


class CompareSequenceDropoutTests(unittest.TestCase):
    def test_recorded_proposals_and_one_induced_dropout_are_separate(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "source.json"
            rows = []
            for i, (frame, index) in enumerate(((260, 0), (267, 1), (273, 1), (279, 2))):
                rows.append(
                    dict(
                        frame=frame,
                        seconds=10 + i * 0.2,
                        candidate_indices=[index, 15],
                        candidate_inliers=[50, 20],
                    )
                )
            source.write_text(
                json.dumps(
                    dict(
                        same_recording=True,
                        physical_actions=0,
                        reference_times=[i * 0.5 for i in range(16)],
                        multi_candidate={"samples": rows},
                    )
                )
            )
            result = run(source, base / "output")
            self.assertTrue(result["synthetic_dropout"])
            self.assertEqual(result["different_decisions"][0]["baseline"], "hypothesis")
            self.assertEqual(result["different_decisions"][0]["current"], "ambiguous")
            self.assertEqual(result["different_decisions"][0]["held_previous"], (15,))
            self.assertFalse(result["execution_qualified"])

    def test_irregular_replay_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "source.json"
            source.write_text(
                json.dumps(
                    dict(
                        same_recording=True,
                        physical_actions=0,
                        reference_times=[i * 0.5 for i in range(16)],
                        multi_candidate={
                            "samples": [
                                dict(
                                    frame=270,
                                    seconds=0,
                                    candidate_indices=[0],
                                    candidate_inliers=[30],
                                ),
                                dict(
                                    frame=279,
                                    seconds=1,
                                    candidate_indices=[15],
                                    candidate_inliers=[30],
                                ),
                            ]
                        },
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "unsupported_replay_order_or_gap"):
                run(source, base / "output")
