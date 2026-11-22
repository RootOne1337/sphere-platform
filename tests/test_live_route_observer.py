import asyncio
import json
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from motor_worker.policy import PolicyFrame
from scripts.pilot.live_route_observer import LatestPreview, Observer


class LatestPreviewTests(unittest.TestCase):
    def test_only_latest_fresh_same_frame_result_is_visible_with_no_fifo(self):
        now = [1.0]
        preview = LatestPreview(clock=lambda: now[0])
        epoch = str(uuid.uuid4())

        def frame(seq, t):
            return PolicyFrame(epoch, seq, t, 1, 1, b"abc")

        self.assertTrue(preview.publish(frame(1, 1.0), {"state": "localized"}))
        self.assertTrue(preview.publish(frame(2, 1.0), {"state": "unknown"}))
        self.assertEqual(preview.read()["sequence"], 2)
        self.assertEqual(preview.read()["state"], "unknown")
        self.assertFalse(preview.publish(frame(1, 1.0), {"state": "localized"}))
        now[0] = 1.41
        self.assertIsNone(preview.read())
        self.assertFalse(preview.publish(frame(3, 1.0), {}))
        self.assertTrue(preview.publish(frame(4, 1.41), {}))
        preview.clear()
        self.assertIsNone(preview.read())

    def test_one_shot_manual_start_preserves_rate_and_refuses_duplicate_or_resource_failure(self):
        with TemporaryDirectory() as folder:
            observer = Observer(object(), "device", "token", Path(folder) / "result.json")
            with (
                patch("scripts.pilot.live_route_observer.collect", return_value={}),
                patch("scripts.pilot.live_route_observer.evaluate", return_value=["low_ram"]),
            ):
                with self.assertRaises(ValueError):
                    observer.start(5)
            self.assertFalse(observer.used)
            with self.assertRaises(ValueError):
                observer.start(5, "unrecognized")
            self.assertFalse(observer.used)
            with (
                patch("scripts.pilot.live_route_observer.collect", return_value={}),
                patch("scripts.pilot.live_route_observer.evaluate", return_value=[]),
                patch("scripts.pilot.live_route_observer.threading.Thread") as thread,
            ):
                observer.start(5)
                thread.return_value.start.assert_called_once()
                with self.assertRaises(ValueError):
                    observer.start(5)


class ObserverBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_localizer_uses_the_receivers_perf_clock_not_windows_tick_count(self):
        epoch = str(uuid.uuid4())
        original = PolicyFrame(epoch, 1, time.perf_counter(), 1, 1, b"abc")

        class Session:
            def __init__(self, config):
                self.config = config
                self.control = None

            async def run(self, _token):
                await asyncio.sleep(0.05)

            def read_rgb(self, after_sequence, **_kwargs):
                return original if after_sequence == 0 else None

            async def close(self):
                pass

            def report(self):
                return {}

        with TemporaryDirectory() as folder:
            observer = Observer(object(), str(uuid.uuid4()), "token", Path(folder) / "result.json")
            with (
                patch("scripts.pilot.live_route_observer.HeadlessSession", Session),
                patch("scripts.pilot.live_route_observer.RouteLocalizer") as tracker,
                patch(
                    "scripts.pilot.live_route_observer.encode_preview",
                    return_value={"state": "unknown"},
                ),
            ):
                tracker.return_value.epoch = epoch
                tracker.return_value.observe.return_value.state = "unknown"
                await observer.observe(5)
                self.assertIs(tracker.call_args.kwargs["clock"], time.perf_counter)
                self.assertIs(tracker.return_value.observe.call_args.args[0], original)

    async def test_transport_configuration_cannot_open_native_input_and_cleanup_clears_frame(self):
        seen = []

        class Session:
            def __init__(self, config):
                seen.append(config)
                self.config = config
                self.control = None
                self.closed = False

            async def run(self, _token):
                await asyncio.sleep(0)

            def read_rgb(self, **_kwargs):
                return None

            async def close(self):
                self.closed = True

            def report(self):
                return {"cleanupFinished": self.closed}

        with TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"
            observer = Observer(object(), str(uuid.uuid4()), "token", output)
            with patch("scripts.pilot.live_route_observer.HeadlessSession", Session):
                await observer.observe(5)
            result = json.loads(output.read_bytes())
            self.assertFalse(seen[0].probe_control)
            self.assertTrue(seen[0].publish_rgb)
            self.assertFalse(result["nativeInputChannelCreated"])
            self.assertEqual(result["physicalActions"], 0)
            self.assertTrue(result["transport"]["cleanupFinished"])
            self.assertIsNone(observer.preview.read())
