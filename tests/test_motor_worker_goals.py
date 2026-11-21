"""Exercise stale goal/epoch races before an action chunk can reach an executor."""
import asyncio
import unittest
from dataclasses import replace

from motor_worker.goals import Goal, GoalBoundPolicy, GoalCapabilities, GoalResult
from motor_worker.policy import ActionChunk, GamepadState, PolicyFrame, PolicyRequest, PolicyResult
from motor_worker.protocol import ProtocolError

EPOCH = "414ce0e9-4b93-4f96-b9ca-ee675f53835e"
OTHER = "753fd530-2f19-4e5e-98ba-769863678141"
PROFILE = "5df4805e-fe64-4d39-960c-19ceab206cd6"


def goal(**kwargs):
    return replace(Goal(EPOCH, EPOCH, PROFILE, EPOCH, 20.0, "text", "Walk to the door"), **kwargs)


def request(**kwargs):
    return replace(PolicyRequest(1, PolicyFrame(EPOCH, 1, 9.0, 1, 1, b"\x00" * 3), 15.0), **kwargs)


class Provider:
    capabilities = GoalCapabilities(frozenset(("text", "image_point")))

    def __init__(self):
        self.called = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.transform = lambda result: result

    async def predict_goal(self, r):
        self.called += 1
        self.entered.set()
        await self.release.wait()
        observation = PolicyResult(r.observation.request_id, r.observation.frame.capture_epoch,
                                   r.observation.frame.receiver_sequence,
                                   ActionChunk((GamepadState.neutral(),), 60))
        return self.transform(GoalResult(observation, r.goal))


class GoalTests(unittest.TestCase):
    def test_goal_is_explicit_and_bounded(self):
        for change in ({"text": ""}, {"text": "a" * 2049}, {"text": "a\x00b"},
                       {"kind": "overlay"}, {"point": (0.5, 0.5)}, {"revision": "v1"},
                       {"expires_at": float("nan")}, {"expires_at": True}):
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                goal(**change)
        self.assertEqual(goal(kind="image_point", text=None, point=(0.25, 1)).point, (0.25, 1))
        for point in ((-0.1, 0), (0, 1.1), (True, 0), (float("nan"), 0), [0, 0]):
            with self.subTest(point=point), self.assertRaises(ProtocolError):
                goal(kind="image_point", text=None, point=point)

    def test_capability_cannot_invent_overlay_conditioning(self):
        with self.assertRaises(ProtocolError):
            GoalCapabilities(frozenset(("overlay",)))
        with self.assertRaises(ProtocolError):
            GoalBoundPolicy(object())


class GoalPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 10.0
        self.provider = Provider()
        self.policy = GoalBoundPolicy(self.provider, clock=lambda: self.now)

    async def test_image_only_provider_refuses_goal_before_inference(self):
        self.provider.capabilities = GoalCapabilities(frozenset())
        with self.assertRaisesRegex(ProtocolError, "unsupported_goal"):
            self.policy.set_goal(goal())
        self.assertEqual(self.provider.called, 0)

    async def test_missing_goal_and_epoch_refuse_before_inference(self):
        with self.assertRaisesRegex(ProtocolError, "goal_missing"):
            await self.policy.predict(request())
        self.policy.set_goal(goal(capture_epoch=OTHER))
        with self.assertRaisesRegex(ProtocolError, "epoch_mismatch"):
            await self.policy.predict(request())
        self.assertEqual(self.provider.called, 0)

    async def test_matching_goal_returns_same_bound_result(self):
        self.policy.set_goal(goal())
        result = await self.policy.predict(request())
        self.assertEqual((result.request_id, result.capture_epoch, result.receiver_sequence), (1, EPOCH, 1))
        self.assertEqual(self.provider.called, 1)

    async def test_goal_changes_during_inference_reject_old_result_without_overlap(self):
        self.policy.set_goal(goal())
        self.provider.release.clear()
        pending = asyncio.create_task(self.policy.predict(request()))
        await self.provider.entered.wait()
        self.policy.set_goal(goal(revision=OTHER, text="Walk away from the door"))
        with self.assertRaisesRegex(ProtocolError, "busy"):
            await self.policy.predict(request())
        self.provider.release.set()
        with self.assertRaisesRegex(ProtocolError, "goal_changed"):
            await pending
        result = await self.policy.predict(request(request_id=2))
        self.assertEqual(result.request_id, 2)

    async def test_clear_then_restore_same_goal_still_rejects_outstanding_reply(self):
        self.policy.set_goal(goal())
        self.provider.release.clear()
        pending = asyncio.create_task(self.policy.predict(request()))
        await self.provider.entered.wait()
        self.policy.set_goal(None)
        self.policy.set_goal(goal())
        self.provider.release.set()
        with self.assertRaisesRegex(ProtocolError, "goal_changed"):
            await pending

    async def test_expiry_at_completion_refuses_action(self):
        self.policy.set_goal(goal())
        self.provider.transform = lambda result: (setattr(self, "now", 15.0) or result)
        with self.assertRaisesRegex(ProtocolError, "expired_goal_result"):
            await self.policy.predict(request())

    async def test_profile_goal_and_frame_binding_cannot_be_faked(self):
        self.policy.set_goal(goal())
        for transform in (
            lambda r: replace(r, goal=goal(profile_revision=OTHER)),
            lambda r: replace(r, goal=goal(text="Run somewhere else")),
            lambda r: replace(r, observation=replace(r.observation, request_id=2)),
            lambda r: replace(r, observation=replace(r.observation, capture_epoch=OTHER)),
            lambda r: replace(r, observation=replace(r.observation, receiver_sequence=2)),
        ):
            self.provider.transform = transform
            with self.assertRaisesRegex(ProtocolError, "binding_mismatch"):
                await self.policy.predict(request())

    async def test_invalid_reused_revision_and_expired_request(self):
        self.policy.set_goal(goal())
        with self.assertRaisesRegex(ProtocolError, "revision_reused"):
            self.policy.set_goal(goal(text="different target"))
        with self.assertRaisesRegex(ProtocolError, "expired_policy_goal"):
            self.policy.set_goal(goal(expires_at=10))
        self.policy.set_goal(goal())
        with self.assertRaisesRegex(ProtocolError, "expired_goal_request"):
            await self.policy.predict(request(deadline=10))
        self.assertEqual(self.provider.called, 0)

    async def test_invalid_replacement_clears_previous_goal(self):
        self.policy.set_goal(goal())
        with self.assertRaises(ProtocolError):
            self.policy.set_goal(goal(text="changed under same revision"))
        with self.assertRaisesRegex(ProtocolError, "goal_missing"):
            await self.policy.predict(request())
        self.assertEqual(self.provider.called, 0)

    async def test_changed_provider_capabilities_invalidate_goal(self):
        self.policy.set_goal(goal())
        self.provider.capabilities = GoalCapabilities(frozenset())
        with self.assertRaisesRegex(ProtocolError, "unsupported_goal"):
            await self.policy.predict(request())
        self.assertIsNone(self.policy.goal)
        self.assertEqual(self.provider.called, 0)

    async def test_provider_failure_is_not_retried(self):
        self.policy.set_goal(goal())
        def fail(_):
            raise RuntimeError("inference_failed")
        self.provider.transform = fail
        with self.assertRaises(RuntimeError):
            await self.policy.predict(request())
        self.assertEqual(self.provider.called, 1)
        self.assertFalse(self.policy.active)


if __name__ == "__main__":
    unittest.main()
