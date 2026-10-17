"""Inference overload, wrong lineage and expiry must never turn into input."""

import asyncio
import math
import unittest
from dataclasses import replace

from motor_worker.pointer_probe import PointerProbe, ProbePoint
from motor_worker.policy import (
    BUTTON_TOKENS,
    ActionChunk,
    GamepadState,
    NeutralPolicy,
    PolicyFrame,
    PolicyResult,
    ShadowPolicyLoop,
)
from motor_worker.protocol import ProtocolError
from motor_worker.session import SessionConfig

EPOCH = "753fd530-2f19-4e5e-98ba-769863678141"
OTHER = "414ce0e9-4b93-4f96-b9ca-ee675f53835e"


def prediction(n=2):
    return {
        "j_left": [[0.4, -0.8] for _ in range(n)],
        "j_right": [[-0.2, 0.1] for _ in range(n)],
        "buttons": [[float(i == 18) for i in range(21)] for _ in range(n)],
    }


def frame(seq=1, at=10.0, epoch=EPOCH):
    return PolicyFrame(epoch, seq, at, 2, 2, b"\x11\x22\x33" * 4)


class PolicyContractTests(unittest.TestCase):
    def test_shadow_mode_cannot_be_combined_with_physical_pointer_probe(self):
        probe = PointerProbe(2, 2, (ProbePoint(0, 0, 0, 0), ProbePoint(100, 1, 0, 0)))
        with self.assertRaisesRegex(ProtocolError, "invalid_shadow_policy_option"):
            SessionConfig(
                "http://127.0.0.1:3015",
                EPOCH,
                probe_control=True,
                pointer_probe=probe,
                shadow_policy=True,
            )

    def test_exact_nitrogen_decoded_columns_and_axes_are_preserved(self):
        chunk = ActionChunk.from_nitrogen(prediction(), ticks_per_second=60)
        self.assertEqual(len(BUTTON_TOKENS), 21)
        self.assertEqual(BUTTON_TOKENS[18], "SOUTH")
        self.assertEqual(BUTTON_TOKENS[11:14], ("RIGHT_BOTTOM", "RIGHT_LEFT", "RIGHT_RIGHT"))
        self.assertEqual(chunk.states[0].left, (0.4, -0.8))
        self.assertEqual(chunk.states[0].right, (-0.2, 0.1))
        self.assertEqual(chunk.states[0].buttons[18], 1)

    def test_invalid_model_columns_and_numeric_values_fail_without_clipping(self):
        invalid = [
            prediction(0),
            prediction(19),
            prediction() | {"extra": 1},
            prediction() | {"j_right": [[0.0, 0.0]]},
        ]
        for v in [True, math.nan, math.inf, 2.0, 10**1000]:
            p = prediction()
            p["j_left"][0][0] = v
            invalid.append(p)
        for v in [True, 0.5, -1, math.nan]:
            p = prediction()
            p["buttons"][0][0] = v
            invalid.append(p)
        for cols in [20, 22]:
            p = prediction()
            p["buttons"][0] = [0.0] * cols
            invalid.append(p)
        for p in invalid:
            with self.subTest(case=str(p)[:80]), self.assertRaises(ProtocolError):
                ActionChunk.from_nitrogen(p, ticks_per_second=60)
        for rate in [True, 0, 121, math.nan, 10**1000]:
            with self.assertRaises(ProtocolError):
                ActionChunk.from_nitrogen(prediction(), ticks_per_second=rate)
        with self.assertRaises(ProtocolError):
            ActionChunk.from_nitrogen(prediction(16), ticks_per_second=5)

    def test_official_checkpoint_horizon_is_not_the_denoising_step_count(self):
        data = prediction(18)
        chunk = ActionChunk.from_nitrogen(data, ticks_per_second=60)
        self.assertEqual(len(chunk.states), 18)
        self.assertEqual(chunk.states[-1].buttons[18], 1)
        self.assertEqual(chunk.preview_at(0.3), GamepadState.neutral())

    def test_hold_timeline_uses_explicit_rate_and_does_not_restart_late_chunk(self):
        state = ActionChunk.from_nitrogen(prediction(1), ticks_per_second=20).states[0]
        chunk = ActionChunk((state, state, GamepadState.neutral()), 20)
        self.assertEqual(chunk.preview_at(0.001), state)
        self.assertEqual(chunk.preview_at(0.099), state)
        self.assertEqual(chunk.preview_at(0.11), GamepadState.neutral())
        self.assertEqual(chunk.preview_at(1), GamepadState.neutral())
        for elapsed in [-1, True, math.nan, 10**1000]:
            with self.assertRaises(ProtocolError):
                chunk.preview_at(elapsed)

    def test_frame_is_bounded_original_rgb_with_valid_receiver_identity(self):
        self.assertEqual(len(frame().rgb24), 12)
        for changes in [
            dict(capture_epoch="0" * 36),
            dict(receiver_sequence=True),
            dict(width=4097),
            dict(height=0),
            dict(rgb24=bytearray(12)),
            dict(rgb24=b"\0" * 11),
            dict(received_at=math.nan),
            dict(received_at=10**1000),
        ]:
            with self.subTest(changes=changes), self.assertRaises(ProtocolError):
                replace(frame(), **changes)


class ControlledPolicy:
    def __init__(self):
        self.requests = []
        self.futures = {}

    async def predict(self, req):
        self.requests.append(req)
        fut = asyncio.get_running_loop().create_future()
        self.futures[req.request_id] = fut
        return await fut

    def finish(self, req, **changes):
        result = PolicyResult(
            req.request_id,
            req.frame.capture_epoch,
            req.frame.receiver_sequence,
            ActionChunk.from_nitrogen(prediction(), ticks_per_second=60),
        )
        self.futures[req.request_id].set_result(replace(result, **changes))


class PolicyLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 10.0
        self.provider = ControlledPolicy()
        self.loop = ShadowPolicyLoop(self.provider, clock=lambda: self.now)
        self.loop.bind_epoch(EPOCH)

    async def asyncTearDown(self):
        await self.loop.close()

    async def launch(self, seq=1, epoch=EPOCH):
        self.loop.offer(frame(seq, self.now, epoch))
        await self.loop.tick()
        await asyncio.sleep(0)

    async def finish(self, req, **changes):
        self.provider.finish(req, **changes)
        await asyncio.sleep(0)
        await self.loop.tick()
        await asyncio.sleep(0)

    async def test_one_active_and_latest_pending_when_model_is_slower_than_camera(self):
        await self.launch()
        req = self.provider.requests[0]
        self.loop.offer(frame(2))
        await self.loop.tick()
        self.loop.offer(frame(3))
        await self.loop.tick()
        self.assertEqual(len(self.provider.requests), 1)
        await self.finish(req)
        self.assertEqual([r.frame.receiver_sequence for r in self.provider.requests], [1, 3])
        await self.finish(self.provider.requests[-1])
        self.assertEqual(self.loop.accepted, 2)
        self.assertEqual(self.loop.replaced, 1)
        self.assertEqual(self.loop.report()["physicalActionsSent"], 0)

    async def test_finished_but_late_result_is_dropped(self):
        await self.launch()
        self.now += 0.3
        await self.finish(self.provider.requests[0])
        self.assertEqual(self.loop.expired_results, 1)
        self.assertEqual(self.loop.accepted, 0)
        self.assertIsNone(self.loop.last_chunk)

    async def test_timeout_cancels_active_before_launching_latest(self):
        await self.launch()
        first_task = self.loop.task
        self.now += 0.3
        self.loop.offer(frame(2, self.now))
        await self.loop.tick()
        await asyncio.sleep(0)
        self.assertTrue(first_task.cancelled())
        self.assertEqual(self.loop.timed_out, 1)
        self.assertEqual([r.frame.receiver_sequence for r in self.provider.requests], [1, 2])

    async def test_rebind_clears_pending_and_rejects_old_inflight_epoch(self):
        await self.launch()
        old = self.provider.requests[0]
        self.loop.offer(frame(2))
        self.loop.bind_epoch(OTHER)
        self.assertIsNone(self.loop.pending)
        self.loop.offer(frame(1, self.now, OTHER))
        await self.finish(old)
        self.assertEqual(self.loop.foreign_results, 1)
        self.assertEqual(self.loop.accepted, 0)
        await self.finish(self.provider.requests[-1])
        self.assertEqual(self.loop.accepted, 1)
        with self.assertRaisesRegex(ProtocolError, "binding_mismatch"):
            self.loop.offer(frame(3))

    async def test_wrong_result_identity_fails_and_is_not_accepted(self):
        await self.launch()
        with self.assertRaisesRegex(ProtocolError, "policy_result_binding_mismatch"):
            await self.finish(self.provider.requests[0], request_id=True)
        self.assertEqual(self.loop.accepted, 0)
        self.assertIsNone(self.loop.last_chunk)

    async def test_epoch_round_trip_does_not_reaccept_old_inflight_result(self):
        await self.launch()
        old = self.provider.requests[0]
        self.loop.bind_epoch(OTHER)
        self.loop.bind_epoch(EPOCH)
        await self.finish(old)
        self.assertEqual(self.loop.foreign_results, 1)
        self.assertEqual(self.loop.accepted, 0)

    async def test_clock_reversal_cannot_accept_a_result_from_the_future(self):
        await self.launch()
        old = self.provider.requests[0]
        self.now -= 0.1
        await self.finish(old)
        self.assertEqual(self.loop.expired_results, 1)
        self.assertEqual(self.loop.accepted, 0)

    async def test_provider_error_is_fixed_without_remote_exception_text(self):
        await self.launch()
        self.provider.futures[1].set_exception(RuntimeError("secret model path/token"))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(ProtocolError, "^policy_inference_failed$"):
            await self.loop.tick()

    async def test_stale_future_duplicate_and_pending_frame_deadlines(self):
        self.loop.offer(frame(1, self.now - 1))
        self.loop.offer(frame(2, self.now + 1))
        self.assertEqual(self.loop.stale_frames, 2)
        with self.assertRaisesRegex(ProtocolError, "sequence_reused"):
            self.loop.offer(frame(2))
        self.loop.offer(frame(3))
        self.now += 0.6
        await self.loop.tick()
        self.assertEqual(self.loop.stale_frames, 3)
        self.assertFalse(self.provider.requests)

    async def test_close_clears_pending_cancels_active_and_cannot_accept_late(self):
        await self.launch()
        self.loop.offer(frame(2))
        await self.loop.close()
        await self.loop.tick()
        self.assertTrue(self.loop.report()["cleanupConfirmed"])
        self.assertEqual(self.loop.accepted, 0)
        with self.assertRaises(ProtocolError):
            self.loop.offer(frame(3))

    async def test_accepted_preview_expires_without_another_prediction(self):
        await self.launch()
        await self.finish(self.provider.requests[0])
        self.assertIsNotNone(self.loop.last_chunk)
        self.now += 0.3
        await self.loop.tick()
        self.assertIsNone(self.loop.last_chunk)

    async def test_noncooperative_provider_blocks_new_request_and_reports_unknown_cleanup(self):
        release = asyncio.Event()

        class Stubborn:
            async def predict(self, req):
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                return await NeutralPolicy().predict(req)

        self.loop.provider = Stubborn()
        await self.launch()
        self.now += 0.3
        self.loop.offer(frame(2, self.now))
        try:
            with self.assertRaisesRegex(ProtocolError, "policy_cleanup_unconfirmed"):
                await self.loop.tick()
            self.assertEqual(self.loop.submitted, 1)
            self.assertIsNotNone(self.loop.task)
            self.assertTrue(self.loop.closed)
            await self.loop.tick()
            self.assertEqual(self.loop.submitted, 1)
        finally:
            release.set()
            await asyncio.sleep(0)

    async def test_report_tail_is_bounded_and_does_not_contain_pixels(self):
        for i in range(1, 71):
            await self.launch(i)
            await self.finish(self.provider.requests[-1])
        report = self.loop.report()
        self.assertEqual(len(report["samples"]), 64)
        self.assertNotIn("rgb24", report)
        self.assertTrue(all("rgb24" not in sample for sample in report["samples"]))
        self.assertNotIn("buttons", str(report))
