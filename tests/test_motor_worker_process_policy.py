"""Exercise actual binary pipes, deadlines and child retirement without a GPU."""

import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from motor_worker.policy import (
    ActionChunk,
    GamepadState,
    KeyboardMouseState,
    PolicyFrame,
    PolicyRequest,
)
from motor_worker.process_policy import ProcessPolicy, ProcessPolicyConfig
from motor_worker.protocol import ProtocolError
from motor_worker.session import HeadlessSession, SessionConfig

EPOCH = "414ce0e9-4b93-4f96-b9ca-ee675f53835e"
OTHER = "753fd530-2f19-4e5e-98ba-769863678141"
CHILD = Path(__file__).with_name("motor_policy_child.py").resolve()


def request(n=1, *, epoch=EPOCH, sequence=None, budget=0.75):
    now = time.perf_counter()
    return PolicyRequest(
        n,
        PolicyFrame(epoch, n if sequence is None else sequence, now, 2, 2, b"\x11\x22\x33" * 4),
        now + budget,
    )


class P2PContractTests(unittest.TestCase):
    def test_decoded_keys_and_relative_mouse_keep_vocabulary_without_android_translation(self):
        chunk = ActionChunk.from_open_p2p(
            {
                "keys": ["w", "LeftShift"],
                "mouse_buttons": ["0"],
                "mouse_delta_x": 501,
                "mouse_delta_y": -501,
            }
        )
        self.assertEqual(chunk.ticks_per_second, 20)
        self.assertEqual(chunk.preview_at(0).keys, ("w", "LeftShift"))
        self.assertEqual(chunk.preview_at(0.05), KeyboardMouseState.neutral())
        with self.assertRaises(ProtocolError):
            ActionChunk((chunk.states[0], GamepadState.neutral()), 20)

    def test_unknown_duplicate_overfull_and_invalid_mouse_are_not_silently_coerced(self):
        base = {"keys": [], "mouse_buttons": [], "mouse_delta_x": 0, "mouse_delta_y": 0}
        cases = [
            base | {"keys": ["KEYCODE_W"]},
            base | {"keys": ["w", "w"]},
            base | {"keys": ["a", "d", "e", "f", "q"]},
            base | {"keys": [True]},
            base | {"mouse_buttons": [0]},
            base | {"mouse_buttons": ["0", "1", "2"]},
            base | {"extra": 1},
        ]
        cases += [base | {"mouse_delta_x": v} for v in (True, 0.5, 1025, float("nan"))]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                ActionChunk.from_open_p2p(value)


class ProcessPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.providers = []

    async def asyncTearDown(self):
        for provider in self.providers:
            await provider.close()

    async def start(self, mode="valid", adapter="nitrogen-decoded-v1", startup=3):
        provider = ProcessPolicy(
            ProcessPolicyConfig(
                Path(sys.executable).resolve(), CHILD, adapter, (mode, adapter), startup
            )
        )
        self.providers.append(provider)
        await provider.start()
        return provider

    async def test_binary_rgb_reply_and_epoch_reset_through_real_child_without_parent_credentials(
        self,
    ):
        with patch.dict(
            os.environ,
            {
                k: "private test credential"
                for k in ("SPHERE_ACCESS_TOKEN", "HF_TOKEN", "AWS_SECRET_ACCESS_KEY")
            },
        ):
            provider = await self.start()
        first = await provider.predict(request())
        self.assertEqual(len(first.chunk.states), 18)
        self.assertAlmostEqual(first.chunk.states[0].left[0], 17 / 255)
        self.assertEqual(first.chunk.states[0].left[1], 0.01)
        second = await provider.predict(request(2))
        self.assertEqual(second.chunk.states[0].left[1], 0.02)
        reset = await provider.predict(request(3, epoch=OTHER, sequence=1))
        self.assertEqual(reset.chunk.states[0].left[1], 0.01)
        self.assertNotIn("private", json.dumps(provider.report()))
        await provider.close()
        self.assertTrue(provider.report()["cleanupConfirmed"])
        with self.assertRaisesRegex(ProtocolError, "not_startable"):
            await provider.start()

    async def test_p2p_is_a_separate_state_type_with_exact_mouse_and_keys(self):
        provider = await self.start(adapter="open-p2p-150m-decoded-v1")
        result = await provider.predict(request())
        self.assertIs(type(result.chunk.states[0]), KeyboardMouseState)
        self.assertEqual(
            result.chunk.states[0], KeyboardMouseState(("w", "LeftShift"), ("0",), 1, -51)
        )

    async def test_invalid_or_foreign_replies_retire_child_without_accepting_another_frame(self):
        for mode in (
            "wrong_request",
            "bool_request",
            "wrong_sequence",
            "wrong_epoch",
            "extra",
            "nan",
            "invalid_prediction",
            "duplicate",
            "reply_flood",
            "eof",
        ):
            with self.subTest(mode=mode):
                provider = await self.start(mode)
                with self.assertRaises(ProtocolError):
                    await provider.predict(request())
                self.assertEqual(provider.responses, 0)
                self.assertTrue(provider.report()["cleanupConfirmed"])
                with self.assertRaisesRegex(ProtocolError, "unavailable"):
                    await provider.predict(request(2))

    async def test_timeout_and_cancellation_kill_real_child_and_never_restart_it(self):
        for cancel in (False, True):
            provider = await self.start("hang")
            task = asyncio.create_task(provider.predict(request(budget=0.08)))
            if cancel:
                await asyncio.sleep(0.02)
                task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else ProtocolError):
                await task
            self.assertIsNotNone(provider.process.returncode)
            self.assertTrue(provider.report()["cleanupConfirmed"])

    async def test_startup_wrong_version_flood_and_timeout_do_not_leak_child(self):
        for mode in ("wrong_ready", "startup_flood", "startup_hang"):
            with self.subTest(mode=mode), self.assertRaises(ProtocolError):
                await self.start(mode, startup=0.2 if mode == "startup_hang" else 3)
            self.assertTrue(self.providers[-1].report()["cleanupConfirmed"])

    async def test_cancellation_during_spawn_or_startup_reaps_child(self):
        provider = ProcessPolicy(
            ProcessPolicyConfig(
                Path(sys.executable).resolve(),
                CHILD,
                "nitrogen-decoded-v1",
                ("startup_hang", "nitrogen-decoded-v1"),
            )
        )
        self.providers.append(provider)
        task = asyncio.create_task(provider.start())
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(provider.report()["cleanupConfirmed"])

    async def test_overlapping_calls_and_duplicate_requests_cannot_cross_wire(self):
        provider = await self.start("slow")
        task = asyncio.create_task(provider.predict(request()))
        await asyncio.sleep(0)
        with self.assertRaisesRegex(ProtocolError, "unavailable"):
            await provider.predict(request(2))
        await task
        with self.assertRaisesRegex(ProtocolError, "invalid_policy_process_request"):
            await provider.predict(request(1))

    async def test_session_rejects_external_provider_outside_shadow_mode(self):
        provider = await self.start()
        config = SessionConfig("http://127.0.0.1:3015", EPOCH)
        with self.assertRaisesRegex(ProtocolError, "external_policy_requires_shadow_mode"):
            HeadlessSession(config, policy=provider)

    async def test_explicit_close_during_startup_and_prediction_reaps_owned_process(self):
        for during_startup in (True, False):
            if during_startup:
                provider = ProcessPolicy(
                    ProcessPolicyConfig(
                        Path(sys.executable).resolve(),
                        CHILD,
                        "nitrogen-decoded-v1",
                        ("startup_hang", "nitrogen-decoded-v1"),
                    )
                )
                self.providers.append(provider)
                task = asyncio.create_task(provider.start())
            else:
                provider = await self.start("hang")
                task = asyncio.create_task(provider.predict(request()))
            await asyncio.sleep(0)
            await provider.close()
            with self.assertRaises(ProtocolError):
                await task
            self.assertTrue(provider.report()["cleanupConfirmed"])
