import json
import unittest
from dataclasses import replace

from motor_worker.goals import Goal
from motor_worker.policy import PolicyFrame, PolicyRequest
from motor_worker.protocol import ProtocolError
from motor_worker.visual_waypoint import VisualReply, VisualWaypoint, admit_visual_reply

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"
OTHER = "0b59dcba-444f-4daa-9a22-aa1b1294ed98"


class VisualWaypointTests(unittest.TestCase):
    def test_actual_launcher_refusal_with_coordinates_is_inconsistent(self):
        # Real Qwen0.8B/PH011 output, not a hypothetical malformed response.
        raw = '{"status":"not_gameplay","side":"left","x":100,"y":1000}'
        with self.assertRaisesRegex(ProtocolError, "inconsistent_visual_waypoint"):
            VisualWaypoint.parse(raw, finish_reason="stop")

    def test_refusal_must_not_carry_a_motion_target(self):
        for status in ("not_gameplay", "unknown"):
            claim = VisualWaypoint(status, "none", 0, 0)
            self.assertEqual(VisualWaypoint.parse(json.dumps(claim.__dict__), finish_reason="stop"), claim)
            with self.assertRaises(ProtocolError):
                replace(claim, x=100)

    def test_grounded_claim_is_only_a_point_not_a_path(self):
        claim = VisualWaypoint("grounded", "right", 750, 650)
        self.assertEqual(claim.x, 750)
        with self.assertRaises(ProtocolError):
            replace(claim, side="none")

    def test_extra_commands_duplicates_types_and_truncation_are_rejected(self):
        claim = {"status": "grounded", "side": "right", "x": 750, "y": 650}
        for data in (claim | {"command": "tap"}, claim | {"x": True}, claim | {"y": 1001}):
            with self.assertRaises(ProtocolError):
                VisualWaypoint.parse(json.dumps(data), finish_reason="stop")
        with self.assertRaises(ProtocolError):
            VisualWaypoint.parse('{"x":1,"x":2}', finish_reason="stop")
        with self.assertRaises(ProtocolError):
            VisualWaypoint.parse(json.dumps(claim), finish_reason="length")


class VisualAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.goal = Goal(EPOCH, EPOCH, EPOCH, EPOCH, 10, "text", "walk to grass")
        frame = PolicyFrame(EPOCH, 7, 1, 1, 1, b"\0\0\0")
        self.request = PolicyRequest(3, frame, 2)
        self.claim = VisualWaypoint("grounded", "center", 500, 700)
        self.reply = VisualReply(3, EPOCH, 7, self.goal, 1.2, self.claim)

    def admit(self, *, reply=None, request=None, goal=False, now=1.3):
        return admit_visual_reply(
            reply or self.reply, request or self.request,
            self.goal if goal is False else goal, now=now,
        )

    def test_fresh_bound_claim_passes_but_cleared_or_replaced_goal_does_not(self):
        self.assertIs(self.admit(), self.claim)
        self.assertIsNone(self.admit(goal=None))
        self.assertIsNone(self.admit(goal=replace(self.goal, revision=OTHER)))

    def test_reply_for_an_old_frame_or_request_is_not_reused(self):
        for reply in (replace(self.reply, request_id=4), replace(self.reply, capture_epoch=OTHER),
                      replace(self.reply, receiver_sequence=8)):
            self.assertIsNone(self.admit(reply=reply))

    def test_model_latency_and_waiting_consumer_both_count_toward_age(self):
        self.assertIsNone(self.admit(reply=replace(self.reply, completed_at=1.6), now=1.6))
        self.assertIsNone(self.admit(now=1.6))
        self.assertIsNone(self.admit(now=1.1))

    def test_expired_request_or_goal_and_non_gameplay_cannot_pass(self):
        self.assertIsNone(self.admit(request=replace(self.request, deadline=1.3)))
        expired = replace(self.goal, expires_at=1.3)
        self.assertIsNone(self.admit(reply=replace(self.reply, goal=expired), goal=expired))
        self.assertIsNone(self.admit(reply=replace(self.reply, claim=VisualWaypoint("unknown", "none", 0, 0))))

    def test_invalid_reply_metadata_and_budget_are_refused(self):
        with self.assertRaises(ProtocolError):
            replace(self.reply, completed_at=float("nan"))
        with self.assertRaises(ProtocolError):
            admit_visual_reply(self.reply, self.request, self.goal, now=1.3, max_receiver_age=2)

    def test_unvalidated_request_dataclass_does_not_escape_as_an_attribute_error(self):
        for request in (replace(self.request, frame=None), replace(self.request, request_id=True)):
            with self.assertRaises(ProtocolError):
                self.admit(request=request)
