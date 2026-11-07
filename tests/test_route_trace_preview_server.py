import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.serve_route_trace_preview import byte_range, previous_capability


class RangeTests(unittest.TestCase):
    def test_expired_local_url_can_be_preserved_without_accepting_an_external_host_or_input_authority(
        self,
    ):
        with TemporaryDirectory() as folder:
            state = Path(folder) / "state.json"
            value = dict(url="http://127.0.0.1:3349/" + "a" * 32 + "/", port=3349, deviceActions=0)
            state.write_text(json.dumps(value))
            self.assertEqual(previous_capability(state, 3349), "a" * 32)
            for key, bad in [
                ("url", "http://example.test:3349/" + "a" * 32 + "/"),
                ("port", 3350),
                ("deviceActions", 1),
            ]:
                changed = {**value, key: bad}
                state.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    previous_capability(state, 3349)

    def test_browser_seek_ranges_are_bounded_inclusive_and_exact(self):
        self.assertEqual(byte_range(None, 100), (0, 99, False))
        self.assertEqual(byte_range("bytes=10-19", 100), (10, 19, True))
        self.assertEqual(byte_range("bytes=90-", 100), (90, 99, True))
        self.assertEqual(byte_range("bytes=-5", 100), (95, 99, True))
        self.assertEqual(byte_range("bytes=90-1000", 100), (90, 99, True))

    def test_multiple_invalid_or_out_of_bounds_ranges_are_refused(self):
        for header in (
            "bytes=100-200",
            "bytes=50-20",
            "bytes=-0",
            "bytes=-",
            "bytes=1-2,3-4",
            "bytes=abc",
            "a" * 100,
        ):
            with self.subTest(header=header), self.assertRaises(ValueError):
                byte_range(header, 100)
