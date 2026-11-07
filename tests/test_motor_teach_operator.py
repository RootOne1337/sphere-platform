import asyncio
import importlib.util
import unittest
from types import SimpleNamespace

from motor_worker.protocol import ProtocolError, VideoBinding
from motor_worker.teach_operator import LoopbackOperator, ManualTeachSession, OperatorIntent

EPOCH = "b68b9cf7-eefd-4572-80af-16a40b2d6c83"


class OperatorIntentTests(unittest.TestCase):
    def setUp(self):
        self.intent = OperatorIntent()
        self.binding = VideoBinding(EPOCH, 960, 540)
        self.number = 0

    def send(self, action, *, now=1, ready=True, **fields):
        import json
        self.number += 1
        data = dict(type="pointer", sequence=self.number, capture_epoch=EPOCH,
                    action=action, x=100, y=400) | fields
        self.intent.receive(json.dumps(data), now, binding=self.binding, ready=ready)

    def test_moves_coalesce_but_edges_are_preserved(self):
        self.send(0)
        for x in range(100, 140):
            self.send(2, x=x)
        self.send(1)
        self.assertEqual([p[0] for p in self.intent.queue], [0, 2, 1])
        self.assertEqual(self.intent.queue[1][1], 139)
        self.assertFalse(self.intent.held)

    def test_wrong_epoch_or_native_not_ready_cannot_queue_input(self):
        for fields in (dict(ready=False), dict(capture_epoch="wrong"), dict(x=-1), dict(action=True)):
            with self.assertRaises(ProtocolError):
                action = fields.pop("action", 0)
                self.send(action, **fields)
        self.assertFalse(self.intent.queue)

    def test_stop_discards_unsent_edges_and_cannot_be_rearmed(self):
        self.send(0)
        self.intent.receive('{"type":"stop","sequence":2}', 1.1, binding=self.binding, ready=True)
        self.assertTrue(self.intent.stopped)
        self.assertFalse(self.intent.queue)
        with self.assertRaises(ProtocolError):
            self.intent.receive('{"type":"heartbeat","sequence":3}', 1.2, binding=self.binding, ready=True)

    def test_duplicate_messages_and_clock_regression_are_refused(self):
        self.send(0)
        for raw, at in (('{"type":"heartbeat","sequence":1}', 1.2),
                        ('{"type":"heartbeat","sequence":2}', .9),
                        ('{"type":[],"sequence":2}', 1.2)):
            with self.assertRaises(ProtocolError):
                self.intent.receive(raw, at, binding=self.binding, ready=True)

    def test_full_edge_queue_is_a_failure_not_unbounded_recording(self):
        for _ in range(4):
            self.send(0)
            self.send(1)
        with self.assertRaisesRegex(ProtocolError, "operator_edge_backpressure"):
            self.send(0)

    def test_native_ready_without_current_manual_availability_is_insufficient(self):
        session = object.__new__(ManualTeachSession)
        session.admission = SimpleNamespace(ready=True)
        session.closing = False
        session.availability = None
        self.assertFalse(session.manual_ready)
        session.availability = SimpleNamespace(state="busy")
        self.assertFalse(session.manual_ready)
        session.availability = SimpleNamespace(state="manual")
        self.assertTrue(session.manual_ready)


@unittest.skipUnless(importlib.util.find_spec("websockets"), "isolated motor runtime required")
class LoopbackBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_static_page_has_no_sphere_token_and_cross_origin_cannot_open_control(self):
        import urllib.error
        import urllib.request

        from websockets.asyncio.client import connect
        from websockets.exceptions import InvalidStatus

        session = object.__new__(ManualTeachSession)
        session.cleanup_finished = False
        session.operator = OperatorIntent()
        session.operator_connected = False
        session.preview_at = None
        session.admission = session.binding = None
        session.failure = None
        session.config = SimpleNamespace(observation_hz=5)
        session.closing = False
        session.fail = lambda _: None
        session.read_rgb = lambda **_: None
        async with LoopbackOperator(session) as server:
            def page():
                with urllib.request.urlopen(server.url, timeout=2) as response:
                    return response.read().decode(), response.headers
            html, headers = await asyncio.to_thread(page)
            self.assertIn("Обучающий проход", html)
            self.assertIn("HttpOnly", headers["Set-Cookie"])
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertNotIn("SPHERE_ACCESS_TOKEN", html)
            self.assertNotIn(server.secret, html)
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            url = server.url.replace("http:", "ws:")+"/control"
            for origin, cookies in (("https://example.invalid", cookie), (server.url, "")):
                with self.assertRaises(InvalidStatus):
                    async with connect(url, origin=origin, additional_headers={"Cookie": cookies}):
                        pass
            async with connect(url, origin=server.url, additional_headers={"Cookie": cookie}) as ws:
                state = await asyncio.wait_for(ws.recv(), 1)
                self.assertIn('"ready": false', state)
                await ws.send('{"type":"stop","sequence":1}')
                await asyncio.sleep(.02)
                self.assertTrue(session.operator.stopped)
                session.cleanup_finished = True
