"""Pure protocol regressions: also runnable with unittest, without SQL imports."""
import copy
import unittest

from backend.websocket.viewer_input import InvalidViewerInput, viewer_command


class ViewerInputTests(unittest.TestCase):
    def test_missing_coordinate_never_becomes_a_top_left_tap(self):
        for value in ({"type": "click"}, {"type": "click", "x": 15}, {"type": "click", "y": 20}):
            with self.subTest(value=value), self.assertRaises(InvalidViewerInput):
                viewer_command(value)

    def test_numbers_are_never_coerced_from_boolean_float_or_text(self):
        for value in (True, False, 1.0, "15", None, [], {}, float("nan"), float("inf")):
            with self.subTest(value=type(value).__name__), self.assertRaises(InvalidViewerInput):
                viewer_command({"type": "click", "x": value, "y": 20})

    def test_coordinate_integer_bounds_match_the_android_int_wire(self):
        self.assertEqual(viewer_command({"type": "click", "x": 0, "y": 2_147_483_647}),
                         {"type": "touch_tap", "x": 0, "y": 2_147_483_647})
        for value in (-1, 2_147_483_648, 10 ** 100):
            with self.subTest(value=value), self.assertRaises(InvalidViewerInput):
                viewer_command({"type": "click", "x": 10, "y": value})

    def test_every_swipe_endpoint_is_required_even_with_duration(self):
        message = {"type": "swipe", "x1": 10, "y1": 20, "x2": 30, "y2": 40, "duration_ms": 250}
        for key in ("x1", "y1", "x2", "y2"):
            partial = {name: value for name, value in message.items() if name != key}
            with self.subTest(key=key), self.assertRaises(InvalidViewerInput):
                viewer_command(partial)

    def test_legacy_swipe_duration_default_is_preserved_but_explicit_invalid_values_fail(self):
        message = {"type": "swipe", "x1": 10, "y1": 20, "x2": 30, "y2": 40}
        self.assertEqual(viewer_command(message), {**message, "type": "touch_swipe", "duration_ms": 300})
        for value in (0, 60_000):
            self.assertEqual(viewer_command({**message, "duration_ms": value})["duration_ms"], value)
        for value in (-1, 60_001, True, "300", 300.0, None):
            with self.subTest(value=value), self.assertRaises(InvalidViewerInput):
                viewer_command({**message, "duration_ms": value})

    def test_keycode_is_explicit_and_not_a_string_or_boolean(self):
        self.assertEqual(viewer_command({"type": "keyevent", "code": 187}), {"type": "keyevent", "code": 187})
        for value in ({"type": "keyevent"}, {"type": "keyevent", "code": True},
                      {"type": "keyevent", "code": "3"}, {"type": "keyevent", "code": -1}):
            with self.subTest(value=value), self.assertRaises(InvalidViewerInput):
                viewer_command(value)

    def test_text_is_exact_without_stringifying_objects_or_numbers(self):
        text = "Пример 'quoted' 🙂\n"
        self.assertEqual(viewer_command({"type": "text", "text": text}), {"type": "text", "text": text})
        self.assertEqual(viewer_command({"type": "text", "text": ""}), {"type": "text", "text": ""})
        for value in ({"type": "text"}, {"type": "text", "text": 123},
                      {"type": "text", "text": {"private": "value"}}, {"type": "text", "text": True}):
            with self.subTest(value=value), self.assertRaises(InvalidViewerInput):
                viewer_command(value)

    def test_unicode_boundary_and_lone_surrogates_do_not_escape(self):
        text = "🙂" * 65_536
        self.assertEqual(viewer_command({"type": "text", "text": text})["text"], text)
        for value in (text + "🙂", "a" * 65_537, "private\ud800value"):
            with self.subTest(length=len(value)), self.assertRaises(InvalidViewerInput) as error:
                viewer_command({"type": "text", "text": value})
            self.assertEqual(str(error.exception), "invalid_parameter")

    def test_malformed_roots_and_types_have_only_a_fixed_error(self):
        for value in (None, [], True, "private", 123, {}, {"type": []}, {"type": None}):
            with self.subTest(kind=type(value).__name__), self.assertRaises(InvalidViewerInput) as error:
                viewer_command(value)
            self.assertEqual(str(error.exception), "invalid_message")

    def test_unsupported_continuous_message_does_not_claim_injection(self):
        with self.assertRaises(InvalidViewerInput) as error:
            viewer_command({"type": "touch_down", "x": 10, "y": 20})
        self.assertEqual(str(error.exception), "unsupported_message")

    def test_browser_identity_metadata_is_never_forwarded_or_mutated(self):
        message = {"type": "click", "x": 10, "y": 20, "session_id": "spoofed", "tenant_id": "other"}
        original = copy.deepcopy(message)
        self.assertEqual(viewer_command(message), {"type": "touch_tap", "x": 10, "y": 20})
        self.assertEqual(message, original)

    def test_keyframe_and_pong_do_not_become_android_input(self):
        self.assertEqual(viewer_command({"type": "request_keyframe", "session_id": "spoofed"}),
                         {"type": "request_keyframe"})
        self.assertIsNone(viewer_command({"type": "pong"}))


if __name__ == "__main__":
    unittest.main()
