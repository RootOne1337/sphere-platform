"""Explicit, finite human-operated single-pointer teaching over Sphere.

The local console keeps Sphere credentials in Python. It has no auto reconnect,
model or route execution. Origin+HttpOnly cookie bind one localhost operator;
loss of its heartbeat retires native input. Preview and recorded H264 are separate.
"""

import asyncio
import base64
import hashlib
import http.cookies
import json
import secrets
import time
from collections import deque
from dataclasses import replace
from pathlib import Path

from motor_worker.policy import finite
from motor_worker.protocol import ProtocolError, integer, message
from motor_worker.session import HeadlessSession


class OperatorIntent:
    def __init__(self):
        self.sequence = 0
        self.last_pulse = None
        self.held = False
        self.stopped = False
        self.queue = deque()

    def receive(self, raw, now, *, binding, ready):
        data = message(raw, 1024, strict_numbers=True)
        if (not finite(now, 0, float("inf")) or self.stopped
                or self.last_pulse is not None and now < self.last_pulse
                or not integer(data.get("sequence"), self.sequence+1, 2147483647)):
            raise ProtocolError("operator_message_order_or_stopped")
        kind = data.get("type")
        if type(kind) is not str:
            raise ProtocolError("operator_message_type")
        if kind in {"heartbeat", "stop"} and data.keys() == {"type", "sequence"}:
            self.stopped = kind == "stop"
            if self.stopped:
                self.queue.clear()
        elif (kind == "pointer" and ready and binding
                and data.keys() == {"type", "sequence", "capture_epoch", "action", "x", "y"}
                and data["capture_epoch"] == binding.epoch
                and integer(data["action"], 0, 3)
                and integer(data["x"], 0, binding.width-1) and integer(data["y"], 0, binding.height-1)
                and (data["action"] == 0) != self.held):
            if len(self.queue) >= 8:
                raise ProtocolError("operator_edge_backpressure")
            self.held = data["action"] in {0, 2}
            point = (data["action"], data["x"], data["y"], now)
            if data["action"] == 2 and self.queue and self.queue[-1][0] == 2:
                self.queue[-1] = point  # Latest MOVE only; retain discrete edges.
            else:
                self.queue.append(point)
        else:
            raise ProtocolError("operator_input_not_ready_or_invalid")
        self.sequence, self.last_pulse = data["sequence"], now


class ManualTeachSession(HeadlessSession):
    def __init__(self, config, *, recording, native_input_enabled):
        if (native_input_enabled is not True or not config.probe_control
                or not config.publish_rgb or config.shadow_policy or config.pointer_probe is not None
                or recording is None):
            raise ProtocolError("explicit_manual_teaching_required")
        super().__init__(config, recording=recording)
        self.operator = OperatorIntent()
        self.operator_connected = False
        self.manual_events = 0
        self.preview_at = None

    def _pointer_enabled(self):
        return True

    def _control_channel_options(self):
        return {"ordered": True, "maxPacketLifeTime": 200}

    @property
    def manual_ready(self):
        return bool(self.admission and self.admission.ready and self.availability
                    and self.availability.state == "manual" and not self.closing)

    def _probe_complete(self):
        # close_control still has to confirm Android release before COMPLETE.
        return not self.operator.queue and self.admission is not None and self.admission.pending_event is None

    def _tick_pointer_probe(self, now):
        now = time.perf_counter()  # The caller may have awaited capture promotion.
        intent = self.operator
        if not self.manual_ready:
            return  # Legacy READY does not replace current input availability.
        frame = self.frames.latest
        fresh = frame is not None and 0 <= now-frame.received_at <= .25
        if self.admission.held and not fresh:
            self.fail("operator_video_stale")
            return
        if intent.stopped:
            if self.admission.pending_event is None:
                self.config = replace(self.config, duration=max(1, self.monitor_seconds))
            return
        if not self.operator_connected:
            if self.manual_events:
                self.fail("operator_connection_lost")
            return
        if (self.manual_events or intent.queue or self.admission.held) and (
                intent.last_pulse is None or now-intent.last_pulse > .35):
            self.fail("operator_heartbeat_deadline")
            return
        if not intent.queue or self.admission.pending is not None:
            return
        if not fresh:
            self.fail("operator_video_stale")
            return
        action, x, y, offered_at = intent.queue.popleft()
        if not 0 <= now-offered_at <= .2:
            self.fail("operator_command_stale")
            return
        packet = self.admission.pointer(action, x, y, now)
        self._send_control(packet)
        self.manual_events += 1

    def report(self):
        result = super().report()
        result["kind"] = "HUMAN_SINGLE_POINTER_TEACHING_NOT_AUTONOMOUS"
        result["control"]["nativeActionAppliedVerified"] = bool(
            result["success"] and self.manual_events and self.admission
            and self.admission.applied_receipts == self.manual_events and self.release_confirmed
        )
        result["operator"] = dict(native_events=self.manual_events, autonomous=False,
                                  preview_hz=self.config.observation_hz, input_capture="own_native_submissions_and_receipts")
        return result


class LoopbackOperator:
    """One short-lived loopback UI. No files or credentials served to the browser."""

    def __init__(self, session):
        if type(session) is not ManualTeachSession:
            raise ProtocolError("manual_teaching_session_required")
        self.session = session
        self.server = self.connection = None
        self.cookie_name = "sphere_teach_"+secrets.token_hex(8)
        self.secret = secrets.token_hex(32)
        self.url = None

    async def __aenter__(self):
        from websockets.asyncio.server import serve
        self.server = await serve(self._handle, "127.0.0.1", 0, process_request=self._request,
                                  max_size=1024, max_queue=4, write_limit=65536,
                                  ping_interval=None, close_timeout=1, compression=None)
        self.url = f"http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}"
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()

    def _request(self, connection, request):
        host = self.url.removeprefix("http://")
        if request.headers.get("Host") != host:
            return connection.respond(403, "Forbidden")
        if request.path == "/" and request.headers.get("Upgrade", "").lower() != "websocket":
            html = Path(__file__).with_name("teach_operator.html").read_text(encoding="utf-8")
            response = connection.respond(200, html)
            response.headers["Content-Type"] = "text/html; charset=utf-8"
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            script = html.split("<script>", 1)[1].split("</script>", 1)[0]
            digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
            response.headers["Content-Security-Policy"] = (
                f"default-src 'none'; script-src 'sha256-{digest}'; style-src 'unsafe-inline'; "
                f"img-src blob:; connect-src {self.url} ws://{host}; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
            response.headers["Set-Cookie"] = (
                f"{self.cookie_name}={self.secret}; HttpOnly; SameSite=Strict; Path=/control"
            )
            return response
        if request.path != "/control" or request.headers.get("Origin") != self.url:
            return connection.respond(403, "Forbidden")
        try:
            cookies = http.cookies.SimpleCookie(request.headers.get("Cookie", ""))
            supplied = cookies.get(self.cookie_name)
            valid = supplied is not None and secrets.compare_digest(supplied.value, self.secret)
        except (http.cookies.CookieError, ValueError):
            valid = False
        if not valid or self.connection is not None:
            return connection.respond(403, "Forbidden")
        return None

    async def _handle(self, connection):
        # Reserve again after upgrade to reject simultaneous handshakes.
        if self.connection is not None:
            await connection.close(1008, "operator_already_attached")
            return
        self.connection = connection
        self.session.operator_connected = True
        self.session.operator.last_pulse = time.perf_counter()
        sender = asyncio.create_task(self._preview(connection))
        def sender_done(task):
            if not task.cancelled() and task.exception() is not None:
                self.session.fail("operator_preview_failed")
        sender.add_done_callback(sender_done)
        try:
            async for raw in connection:
                now = time.perf_counter()
                ready = bool(self.session.manual_ready
                             and self.session.preview_at is not None and 0 <= now-self.session.preview_at <= .5)
                self.session.operator.receive(raw, now, binding=self.session.binding, ready=ready)
        except ProtocolError as error:
            self.session.fail(str(error))
        except Exception:
            if not self.session.cleanup_finished:
                self.session.fail("operator_transport_closed")
        finally:
            self.session.operator_connected = False
            if not self.session.cleanup_finished and not self.session.operator.stopped:
                self.session.fail("operator_connection_lost")
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
            # Single operator per episode. Never admit a reconnect/replay.

    async def _preview(self, connection):
        import io

        from PIL import Image

        sequence = 0

        def jpeg(frame):
            image = Image.frombytes("RGB", (frame.width, frame.height), frame.rgb24)
            image.thumbnail((960, 540))
            dest = io.BytesIO()
            image.save(dest, "JPEG", quality=75)
            return dest.getvalue()

        while not self.session.cleanup_finished:
            frame = self.session.read_rgb(after_sequence=sequence)
            binding = self.session.binding
            state = dict(type="state", ready=self.session.manual_ready,
                         width=binding.width if binding else None, height=binding.height if binding else None,
                         capture_epoch=binding.epoch if binding else None, failure=self.session.failure,
                         preview_hz=self.session.config.observation_hz)
            async with asyncio.timeout(.25):
                await connection.send(json.dumps(state))
                if frame:
                    sequence = frame.receiver_sequence
                    payload = await asyncio.to_thread(jpeg, frame)
                    if len(payload) > 1024*1024:
                        raise ProtocolError("operator_preview_quota")
                    self.session.preview_at = frame.received_at
                    await connection.send(payload)
            await asyncio.sleep(1/self.session.config.observation_hz)
