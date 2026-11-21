import math
import unittest

from motor_worker.protocol import ProtocolError
from motor_worker.steering import WalkingSteering
from motor_worker.virtual_stick import StickGeometry, VirtualStickContact


class WalkingSteeringTests(unittest.TestCase):
    def observe(self, controller, heading=0, now=1, **kwargs):
        return controller.observe(
            heading, clearance=kwargs.pop("clearance", "clear"),
            received_at=kwargs.pop("received_at", now - 0.02), now=now, **kwargs,
        )

    def test_analog_speed_ramps_and_tight_turn_immediately_reduces_speed(self):
        c = WalkingSteering()
        speeds = [abs(self.observe(c, now=1 + i * 0.2).y) for i in range(6)]
        self.assertEqual(speeds[0], 0)
        self.assertAlmostEqual(speeds[1], 0.2)
        self.assertAlmostEqual(speeds[-1], 0.8)
        turn = self.observe(c, 90, now=2.2)
        self.assertAlmostEqual(turn.x, 0.25)
        self.assertAlmostEqual(turn.y, 0)

    def test_blocked_unknown_and_lost_heading_never_ramp_down_slowly(self):
        for kwargs in ({"clearance": "blocked"}, {"clearance": "unknown"}, {"heading": None}):
            c = WalkingSteering()
            for i in range(6):
                self.observe(c, now=1 + i * 0.2)
            intent = self.observe(c, now=2.2, **kwargs)
            self.assertEqual((intent.x, intent.y, c.speed), (0, 0, 0))

    def test_fresh_frames_still_stop_after_a_processing_gap(self):
        c = WalkingSteering()
        self.observe(c)
        self.observe(c, now=1.4)
        result = self.observe(c, now=2)
        self.assertEqual(result.reason, "observation_stale_or_gap")
        self.assertEqual(result.y, 0)

    def test_caution_and_explicit_zero_cap_are_enforced(self):
        c = WalkingSteering()
        for i in range(6):
            self.observe(c, now=1 + i * 0.2)
        self.assertAlmostEqual(abs(self.observe(c, now=2.2, clearance="caution").y), 0.25)
        self.assertEqual(self.observe(c, now=2.4, speed_cap=0).reason, "speed_cap_zero")

    def test_five_hz_speed_corrections_keep_a_single_android_contact(self):
        c, s = WalkingSteering(), VirtualStickContact(StickGeometry(960, 540, 140, 430, 50))
        events, held = [], False
        for i in range(15):
            now = 1 + i * 0.2
            intent = self.observe(c, 10 if i % 2 else -10, now=now)
            s.observe(intent.x, intent.y, now - 0.02, now)
            for tick in (now, now + 0.02):
                event = s.next_event(tick, tick - 0.01, held=held)
                if event:
                    events.append(event.action)
                    s.sent(event, tick)
                    held = event.action != 1
        self.assertEqual(events.count(0), 1)
        self.assertNotIn(1, events)
        self.assertGreater(events.count(2), 10)

    def test_invalid_configuration_and_observations_do_not_mutate_speed(self):
        for kwargs in ({"acceleration": True}, {"min_deflection": 0.9}, {"max_deflection": 2}):
            with self.assertRaises(ProtocolError):
                WalkingSteering(**kwargs)
        c = WalkingSteering()
        self.observe(c)
        for kwargs in ({"heading": math.nan}, {"speed_cap": True}, {"clearance": []}, {"now": 0.5}):
            with self.assertRaises(ProtocolError):
                self.observe(c, **kwargs)
            self.assertEqual(c.last_now, 1)
