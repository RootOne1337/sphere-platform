import copy
import json
import tempfile
import unittest
from pathlib import Path

from motor_worker.keymap_inspect import LIMIT, inspect_file, inspect_text
from motor_worker.protocol import ProtocolError


class KeymapInspectionTests(unittest.TestCase):
    def setUp(self):
        self.source = dict(
            configInfo=dict(resolutionPattern=dict(width=1600, height=900)),
            keyboardMappings=[
                dict(**{"class": "ClassKeyboardDisc"}, data=dict(
                    origin=dict(x=1503, y=8172), radius=772,
                    leftKey=65, upKey=87, rightKey=68, downKey=83)),
                dict(**{"class": "ClassKeyboardCurve"}, data=dict(
                    key=32, secondKey=0, curve=[dict(x=9300, y=8800, timing=0),
                                               dict(x=9300, y=8800, timing=104)])),
            ])

    def inspect(self, data=None):
        return inspect_text(json.dumps(self.source if data is None else data))

    def test_inspection_preserves_metadata_without_granting_execution_or_geometry(self):
        report = self.inspect()
        self.assertEqual(report["source_geometry"], dict(width=1600, height=900))
        self.assertEqual(report["bindings"][0]["origin"], dict(x=1503, y=8172))
        self.assertEqual(report["bindings"][0]["keys"]["upKey"], 87)
        self.assertFalse(report["bindings"][0]["radius_unit_verified"])
        self.assertFalse(report["bindings"][1]["timing_unit_verified"])
        self.assertFalse(report["complete_for_execution"])
        self.assertTrue(all(v["executable"] is False for v in report["bindings"]))

    def test_macros_remain_opaque_and_their_commands_are_never_emitted_or_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            sentinel = Path(temp)/"must-not-exist"
            script = f"__import__('pathlib').Path({str(sentinel)!r}).write_text('bad')"
            self.source["keyboardMappings"].append(dict(**{"class": "ClassKeyboardMacros"},
                                                       data=dict(key=66, macros=script)))
            report = self.inspect()
            self.assertFalse(sentinel.exists())
            self.assertNotIn(script, json.dumps(report))
            self.assertFalse(report["bindings"][-1]["imported"])
            self.assertEqual(report["opaque_bindings"], 1)

    def test_smp_references_are_read_only_and_not_automatically_resolved(self):
        report = self.inspect(dict(resolutionRelatives={"960x540": dict(keyboardId="Black Russia.kmp", joystickId="")}))
        self.assertEqual(report["references"][0]["keyboardId"], "Black Russia.kmp")
        self.assertFalse(report["references_followed"])
        for filename in ("../foreign.kmp", "C:/other.kmp", "evil\\other.kmp", "a\nb.kmp"):
            with self.assertRaises(ProtocolError):
                self.inspect(dict(resolutionRelatives={"960x540": dict(keyboardId=filename, joystickId="")}))

    def test_empty_override_is_not_mistaken_for_a_keyboard_configuration(self):
        self.source["keyboardMappings"] = []
        report = self.inspect()
        self.assertEqual(report["mappings"], 0)
        self.assertFalse(report["complete_for_execution"])

    def test_outside_geometry_boolean_duplicate_and_regressing_timing_are_refused(self):
        for mutate in (
            lambda d: d["configInfo"]["resolutionPattern"].update(width=True),
            lambda d: d["keyboardMappings"][0]["data"]["origin"].update(x=10001),
            lambda d: d["keyboardMappings"][0]["data"].update(upKey=65),
            lambda d: d["keyboardMappings"][1]["data"]["curve"][1].update(timing=-1),
        ):
            data = copy.deepcopy(self.source)
            mutate(data)
            with self.assertRaises(ProtocolError):
                self.inspect(data)
        with self.assertRaises(ProtocolError):
            inspect_text('{"keyboardMappings":[],"keyboardMappings":[]}')

    def test_unknown_type_is_reported_without_implicit_support(self):
        self.source["keyboardMappings"].append(dict(**{"class": "NewForeignAction"}, data=dict(command="ignored")))
        report = self.inspect()
        self.assertFalse(report["bindings"][-1]["recognized"])
        self.assertEqual(report["opaque_bindings"], 1)

    def test_file_bom_hash_and_bytes_are_bound_without_filename_resolution_assumption(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"profile_960x540.kmp"
            path.write_text(json.dumps(self.source), encoding="utf-8-sig")
            result = inspect_file(path)
            self.assertEqual(result["source_bytes"], path.stat().st_size)
            self.assertEqual(len(result["source_sha256"]), 64)
            self.assertEqual(result["source_geometry"]["width"], 1600)
            path.write_bytes(b"x"*(LIMIT+1))
            with self.assertRaisesRegex(ProtocolError, "keymap_file_quota"):
                inspect_file(path)

    def test_mapping_point_and_macro_quotas_are_bounded(self):
        for count, macro in ((129, ""), (1, "x"*16385)):
            data = copy.deepcopy(self.source)
            data["keyboardMappings"] = [dict(**{"class": "ClassKeyboardMacros"}, data=dict(key=66, macros=macro))]*count
            with self.assertRaises(ProtocolError):
                self.inspect(data)
        self.source["keyboardMappings"][1]["data"]["curve"] *= 513
        with self.assertRaises(ProtocolError):
            self.inspect()
