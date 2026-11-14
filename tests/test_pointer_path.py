"""No device/DB: contract parity and version admission for every task producer."""
import copy
import json
import unittest
from pathlib import Path

from backend.schemas.pointer_path import pointer_path_admission_error, valid_pointer_path


class PointerPathTest(unittest.TestCase):
    def test_shared_contract(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/action-parameters.v1.json").read_text(encoding="utf-8"))
        self.assertTrue(valid_pointer_path(fixture["valid_actions"]["pointer_path"]["path"]))
        for case in fixture["cases"]:
            if case["name"].startswith("path-"):
                with self.subTest(case=case["name"]):
                    self.assertFalse(valid_pointer_path(case["action"]["path"]))

    def test_admission_rejects_old_and_unknown_agents_including_nested_actions(self):
        for dag in ({"nodes":[{"action":{"type":"pointer_path"}}]}, {"nodes":[{"action":{"type":"loop","body":[{"action":{"type":"pointer_path"}}]}}]}):
            original = copy.deepcopy(dag)
            for version in (None,1,10280):
                self.assertIn("no input was sent",pointer_path_admission_error(dag,version))
            for version in (10281,10282):
                self.assertIsNone(pointer_path_admission_error(dag,version))
            self.assertEqual(dag,original)
        self.assertIsNone(pointer_path_admission_error({"nodes":[{"action":{"type":"tap"}}]},None))

    def test_boolean_geometry_timestamps_and_more_than_4096_points_rejected(self):
        fixture = json.loads((Path(__file__).parent / "fixtures/action-parameters.v1.json").read_text(encoding="utf-8"))
        path=fixture["valid_actions"]["pointer_path"]["path"]
        for field in ("schema_version","frame_width","frame_height"):
            bad = copy.deepcopy(path)
            bad[field] = True
            self.assertFalse(valid_pointer_path(bad))
        bad = copy.deepcopy(path)
        bad["points"] = bad["points"] * 1025
        self.assertFalse(valid_pointer_path(bad))
