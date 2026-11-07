"""Local GPS geometry must not shortcut corners, guess forks or imply arrival."""

import asyncio
import importlib.util
import json
import math
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from motor_worker.minimap import MinimapProfile, MinimapRouteShadow, extract_route
from motor_worker.policy import GamepadState, PolicyFrame, PolicyRequest
from motor_worker.protocol import ProtocolError
from motor_worker.session import HeadlessSession, SessionConfig
from motor_worker.stick_execution import StickPolicySession, StickProfile
from motor_worker.virtual_stick import StickGeometry

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
OTHER = "414ce0e9-4b93-4f96-b9ca-ee675f53835e"
AVAILABLE = all(importlib.util.find_spec(m) for m in ("cv2", "numpy"))


def profile(**changes):
    return replace(
        MinimapProfile(
            160,
            120,
            (12, 10, 96, 96),
            (48, 48),
            44,
            6,
            (140, 160, 120),
            (160, 255, 255),
            forward_degrees=0,
        ),
        **changes,
    )


def pixels(lines=(), color=(230, 20, 230), sequence=1, at=10, epoch=EPOCH):
    import cv2
    import numpy as np

    image = np.zeros((120, 160, 3), dtype=np.uint8)
    for a, b, width in lines:
        cv2.line(image, a, b, color, width)
    return PolicyFrame(epoch, sequence, at, 160, 120, image.tobytes())


class MinimapProfileTests(unittest.TestCase):
    def test_shipped_profile_is_versioned_and_does_not_assume_a_heading(self):
        path = Path(__file__).resolve().parents[1] / "examples/motor-minimap-profile.json"
        parsed = MinimapProfile.parse(path.read_text(encoding="utf-8"))
        self.assertIsNone(parsed.forward_degrees)
        self.assertEqual((parsed.frame_width, parsed.frame_height), (960, 540))

    def test_schema_rejects_duplicates_extra_missing_fields_and_boolean_version(self):
        data = {"schema_version": 1, **asdict(profile())}
        invalid = [
            data | {"schema_version": True},
            data | {"extra": 1},
            {k: v for k, v in data.items() if k != "forward_degrees"},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                MinimapProfile.parse(json.dumps(value))
        raw = json.dumps(data)
        with self.assertRaisesRegex(ProtocolError, "invalid_json"):
            MinimapProfile.parse(raw[:-1] + ', "schema_version": 1}')

    def test_profile_size_arrays_and_geometry_are_bounded(self):
        data = {"schema_version": 1, **asdict(profile())}
        for changes in (
            dict(roi="12,10,96,96"),
            dict(center=[False, 48]),
            dict(hsv_upper=[200, 255, 255]),
            dict(lookahead_px=math.inf),
            dict(forward_degrees=math.nan),
            dict(forward_degrees=math.inf),
        ):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                MinimapProfile.parse(json.dumps(data | changes))
        with self.assertRaises(ProtocolError):
            MinimapProfile.parse(" " * 4097 + json.dumps(data))


@unittest.skipUnless(AVAILABLE, "optional motor vision dependencies required")
class MinimapGeometryTests(unittest.TestCase):
    def test_straight_route_is_anchored_at_player_and_uses_original_frame_coordinates(self):
        result = extract_route(pixels([((60, 58), (60, 15), 3)]), profile())
        self.assertTrue(result.direction_available, result)
        self.assertAlmostEqual(result.heading_error_degrees, 0, delta=4)
        self.assertGreater(result.path_length_px, 27)
        self.assertTrue(all(12 <= x < 108 and 10 <= y < 106 for x, y in result.path))
        self.assertLess(result.path[-1][1], result.path[0][1])

    def test_right_angle_follows_connected_pixels_instead_of_a_chord(self):
        import numpy as np

        frame = pixels([((60, 58), (60, 37), 3), ((60, 37), (93, 37), 3)])
        result = extract_route(frame, profile(lookahead_px=42))
        self.assertTrue(result.direction_available, result)
        self.assertGreater(result.heading_error_degrees, 25)
        self.assertLess(result.heading_error_degrees, 75)
        image = np.frombuffer(frame.rgb24, dtype=np.uint8).reshape(120, 160, 3)
        self.assertTrue(all(image[y, x, 0] == 230 for x, y in result.path))
        self.assertGreater(len(result.path), 20)

    def test_fork_is_not_resolved_by_arbitrarily_selecting_a_longer_branch(self):
        frame = pixels([((60, 58), (60, 43), 3), ((60, 43), (35, 22), 3), ((60, 43), (89, 20), 3)])
        result = extract_route(frame, profile(lookahead_px=35))
        self.assertEqual(result.reason, "route_frontier_ambiguous")
        self.assertFalse(result.direction_available)
        self.assertFalse(result.path)

    def test_two_disconnected_nearby_routes_are_ambiguous_at_the_anchor(self):
        frame = pixels([((55, 50), (35, 20), 2), ((65, 50), (88, 20), 2)])
        self.assertEqual(extract_route(frame, profile()).reason, "route_anchor_ambiguous")

    def test_gap_is_not_morphologically_filled_or_reported_as_arrival(self):
        frame = pixels([((60, 58), (60, 48), 2), ((60, 35), (60, 15), 2)])
        result = extract_route(frame, profile())
        self.assertEqual(result.reason, "route_too_short_not_arrival")
        self.assertFalse(result.direction_available)

    def test_missing_route_distant_marker_and_outside_roi_hud_are_not_a_route(self):
        for frame in (
            pixels(),
            pixels([((60, 21), (60, 15), 3)]),
            pixels([((130, 100), (130, 10), 3)]),
        ):
            with self.subTest(frame=frame.receiver_sequence):
                self.assertEqual(extract_route(frame, profile()).reason, "route_not_anchored")

    def test_unknown_orientation_keeps_geometry_but_does_not_claim_a_direction(self):
        result = extract_route(pixels([((60, 58), (60, 15), 3)]), profile(forward_degrees=None))
        self.assertEqual(result.reason, "orientation_not_calibrated")
        self.assertTrue(result.path)
        self.assertIsNone(result.heading_error_degrees)
        self.assertFalse(result.direction_available)

    def test_calibrated_heading_rotates_error_without_changing_path(self):
        frame = pixels([((60, 58), (60, 15), 3)])
        north = extract_route(frame, profile())
        east = extract_route(frame, profile(forward_degrees=90))
        self.assertEqual(east.path, north.path)
        self.assertAlmostEqual(east.heading_error_degrees, -90, delta=4)

    def test_red_wraparound_and_rgb_channel_order_are_explicit(self):
        red = profile(hsv_lower=(170, 160, 120), hsv_upper=(10, 255, 255))
        frame = pixels([((60, 58), (60, 15), 3)], color=(240, 20, 20))
        self.assertTrue(extract_route(frame, red).direction_available)
        blue = pixels([((60, 58), (60, 15), 3)], color=(20, 20, 240))
        self.assertFalse(extract_route(blue, red).direction_available)

    def test_dense_matching_hud_is_refused_before_graph_search(self):
        frame = pixels([((20, 58), (100, 58), 65)])
        self.assertEqual(extract_route(frame, profile()).reason, "route_mask_too_dense")

    def test_wrong_resolution_or_malformed_calibration_is_refused(self):
        frame = pixels()
        with self.assertRaises(ProtocolError):
            extract_route(frame, profile(frame_width=161))
        for changes in (
            dict(roi=(0, 0, 400, 96)),
            dict(center=(2, 2)),
            dict(player_radius=44),
            dict(hsv_lower=(True, 0, 0)),
            dict(hsv_upper=(200, 255, 255)),
            dict(forward_degrees=math.nan),
            dict(lookahead_px=2),
            dict(min_path_px=100),
            dict(hsv_lower=(140, 255, 255), hsv_upper=(160, 0, 0)),
        ):
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                profile(**changes)


@unittest.skipUnless(AVAILABLE, "optional motor vision dependencies required")
class MinimapShadowTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_session_rejects_even_idle_native_admission_for_route_observer(self):
        with self.assertRaisesRegex(ProtocolError, "minimap_analysis_forbids_native_admission"):
            HeadlessSession(
                SessionConfig(
                    "http://127.0.0.1:3015", EPOCH, probe_control=True, shadow_policy=True
                ),
                policy=MinimapRouteShadow(profile(), goal_revision=OTHER),
            )

    async def test_analysis_failure_is_not_raised_again_during_cleanup(self):
        observer = MinimapRouteShadow(
            profile(frame_width=161), goal_revision=OTHER, clock=lambda: 10.1
        )
        with self.assertRaisesRegex(ProtocolError, "minimap_frame_geometry_mismatch"):
            await observer.predict(PolicyRequest(1, pixels(), 10.4))
        await observer.close()
        self.assertTrue(observer.report()["backgroundJobRetired"])
        self.assertFalse(observer.report()["samples"])

    async def test_real_policy_binding_returns_only_neutral_and_bounded_diagnostics(self):
        now = 10.1
        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: now)
        for n in range(1, 71):
            frame = pixels([((60, 58), (60, 15), 3)], sequence=n)
            reply = await observer.predict(PolicyRequest(n, frame, 10.4))
            self.assertEqual(
                (reply.request_id, reply.capture_epoch, reply.receiver_sequence), (n, EPOCH, n)
            )
            self.assertEqual(reply.chunk.states, (GamepadState.neutral(),))
        report = observer.report()
        self.assertFalse(report["physicalExecutionSupported"])
        self.assertEqual(report["reasons"], {"route_observed": 70})
        self.assertEqual(len(report["samples"]), 64)
        self.assertNotIn("rgb24", str(report))
        self.assertFalse(report["obstacleClearanceMeasured"])
        self.assertFalse(report["arrivalMeasured"])

    async def test_capture_change_is_terminal_even_if_old_epoch_returns(self):
        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: 10.1)
        for seq, epoch in ((1, EPOCH), (1, OTHER), (2, EPOCH)):
            await observer.predict(PolicyRequest(seq, pixels(sequence=seq, epoch=epoch), 10.4))
        self.assertEqual(observer.report()["reasons"]["route_session_changed"], 2)

    async def test_stale_frame_or_analysis_cannot_produce_a_fresh_route(self):
        from unittest.mock import patch

        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: 11)
        await observer.predict(PolicyRequest(1, pixels(), 11.3))
        self.assertEqual(observer.report()["reasons"], {"route_frame_stale": 1})
        times = iter((10.05, 10.3))
        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: next(times))
        with patch("motor_worker.minimap.extract_route", wraps=extract_route):
            await observer.predict(PolicyRequest(2, pixels(sequence=2), 10.2))
        self.assertEqual(observer.report()["reasons"], {"route_analysis_expired": 1})

    async def test_shadow_provider_cannot_be_used_as_a_physical_stick_policy(self):
        with self.assertRaisesRegex(ProtocolError, "explicit_stick_execution_required"):
            StickPolicySession(
                SessionConfig(
                    "http://127.0.0.1:3015", EPOCH, probe_control=True, shadow_policy=True
                ),
                profile=StickProfile(StickGeometry(160, 120, 30, 90, 10), "gamepad_left"),
                policy=MinimapRouteShadow(profile(), goal_revision=OTHER),
                scene_guard=lambda _: True,
                execution_enabled=True,
            )

    async def test_analysis_runs_off_event_loop(self):
        import threading
        from unittest.mock import patch

        origin, observed = threading.get_ident(), []

        def check(frame, config):
            observed.append(threading.get_ident())
            return extract_route(frame, config)

        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: 10.1)
        with patch("motor_worker.minimap.extract_route", side_effect=check):
            await asyncio.wait_for(observer.predict(PolicyRequest(1, pixels(), 10.4)), 2)
        self.assertNotEqual(observed, [origin])

    async def test_cancel_joins_real_cpu_work_and_refuses_overlapping_requests(self):
        import threading
        from unittest.mock import patch

        entered, release = threading.Event(), threading.Event()

        def blocked(frame, config):
            entered.set()
            release.wait(timeout=3)
            return extract_route(frame, config)

        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: 10.1)
        with patch("motor_worker.minimap.extract_route", side_effect=blocked):
            task = asyncio.create_task(observer.predict(PolicyRequest(1, pixels(), 10.4)))
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait), 1)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertFalse(observer.report()["backgroundJobRetired"])
                with self.assertRaisesRegex(ProtocolError, "route_analysis_busy"):
                    await observer.predict(PolicyRequest(2, pixels(sequence=2), 10.4))
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
        await observer.close()
        self.assertTrue(observer.report()["backgroundJobRetired"])
        self.assertFalse(observer.report()["samples"])

    async def test_outer_loop_cannot_attest_cleanup_until_cpu_job_actually_retires(self):
        import threading
        from unittest.mock import patch

        from motor_worker.policy import ShadowPolicyLoop

        entered, release = threading.Event(), threading.Event()

        def blocked(frame, config):
            entered.set()
            release.wait(timeout=3)
            return extract_route(frame, config)

        observer = MinimapRouteShadow(profile(), goal_revision=OTHER, clock=lambda: 10.1)
        loop = ShadowPolicyLoop(observer, clock=lambda: 10.1, cleanup_timeout=0.01)
        loop.bind_epoch(EPOCH)
        with patch("motor_worker.minimap.extract_route", side_effect=blocked):
            loop.offer(pixels())
            await loop.tick()
            try:
                await asyncio.wait_for(asyncio.to_thread(entered.wait), 1)
                with self.assertRaisesRegex(ProtocolError, "policy_cleanup_unconfirmed"):
                    await loop.close()
                self.assertFalse(loop.report()["cleanupConfirmed"])
                self.assertFalse(observer.report()["backgroundJobRetired"])
                self.assertTrue(loop.closed)
            finally:
                release.set()
                await observer.close()
                await asyncio.sleep(0)
                await loop.close()
        self.assertTrue(loop.report()["cleanupConfirmed"])
        self.assertEqual(loop.accepted, 0)
