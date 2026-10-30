"""Preview geometry and request-boundary tests; no GPU, download or Android."""
import io
import json
import threading
from email.message import Message
from http.client import HTTPConnection
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot.teaching_scene import (
    MAX_BODY,
    MAX_SESSION_SECONDS,
    Handler,
    PreviewServer,
    unproject,
)


def test_unproject_world_to_camera_and_filter_invalid_depth():
    depth = np.ones((100, 100), dtype=np.float32) * 2
    depth[30, 30] = np.nan
    extrinsics = np.c_[np.eye(3), [1, 0, 0]]
    points, colors = unproject(depth, np.ones_like(depth), np.eye(3), extrinsics, np.zeros((100, 100, 3), dtype=np.uint8))
    assert len(points) > 0 and np.isfinite(points).all()
    assert np.all(points[:, 2] == 2)
    assert np.all(points[:, 0] % 4 == 3)  # camera x=2*pixel; world x=camera x-1
    assert len(colors) == len(points)


@pytest.fixture
def service():
    class Geometry:
        previous = None

        def reset(self, recording_id):
            self.recording_id = recording_id

    # Ephemeral loopback port; production constructor binds only 3332.
    instance = PreviewServer.__new__(PreviewServer)
    super(PreviewServer, instance).__init__(("127.0.0.1", 0), Handler)
    instance.origin = "http://127.0.0.1:3015"
    instance.lock = threading.Lock()
    instance.geometry, instance.session = Geometry(), None
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield instance
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=2)


def post(service, headers, path="/session", body=b"{}"):
    connection = HTTPConnection("127.0.0.1", service.server_port, timeout=2)
    connection.request("POST", path, body, {"Host": "127.0.0.1:3332", **headers})
    response = connection.getresponse()
    status, data = response.status, json.loads(response.read())
    connection.close()
    return status, data


def test_origin_and_session_ownership_are_required(service):
    assert post(service, {"Origin": "https://other.example"})[0] == 403
    headers = {"Origin": service.origin, "X-Sphere-Preview": "1", "Content-Type": "application/json"}
    body = json.dumps({"device_id": "414ce0e9-4b93-4f96-b9ca-ee675f53835e"}).encode()
    status, session = post(service, headers, body=body)
    assert status == 200 and len(session["key"]) == 64
    assert post(service, headers, body=body)[0] == 409
    assert post(service, headers, path="/frame?sequence=1")[0] == 403
    assert post(service, {**headers, "Host": "rebound.example:3332"})[0] == 403


def test_busy_request_is_rejected_without_an_inference_queue(service):
    service.lock.acquire()
    try:
        for _ in range(8):
            status, data = post(service, {"Origin": service.origin, "X-Sphere-Preview": "1"}, body=b"x"*16384)
            assert status == 409 and data["error"] == "busy_no_queue"
    finally:
        service.lock.release()


def test_busy_reply_consumes_bounded_body_without_waiting_for_inference():
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(origin="http://127.0.0.1:3015", lock=threading.Lock())
    handler.server.lock.acquire()
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    handler.headers = Message()
    for key, value in {"Origin": handler.server.origin, "Host": "127.0.0.1:3332",
                       "X-Sphere-Preview": "1", "Content-Length": "16384"}.items():
        handler.headers[key] = value
    handler.rfile = io.BytesIO(b"x"*16384)
    results = []

    def respond(status, data):
        assert handler.rfile.tell() == 16384
        results.append((status, data))

    handler.respond = respond
    handler.do_POST()
    assert results == [(409, {"error": "busy_no_queue"})]
    assert handler.server.lock.locked()


@pytest.mark.parametrize("lengths,transfer", [([str(MAX_BODY+1)], None), (["2", "2"], None),
                                           (["-1"], None), (["2"], "chunked")])
def test_body_budget_or_ambiguous_framing_never_reads_payload(lengths, transfer):
    handler = Handler.__new__(Handler)
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    handler.headers = Message()
    for value in lengths:
        handler.headers["Content-Length"] = value
    if transfer:
        handler.headers["Transfer-Encoding"] = transfer
    handler.rfile = io.BytesIO(b"xx")
    results = []
    handler.respond = lambda status, _: results.append(status)
    handler.do_POST()
    assert results == [400] and handler.rfile.tell() == 0


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_disconnected_browser_does_not_turn_a_valid_response_into_model_failure(stage):
    handler = Handler.__new__(Handler)
    handler.server = SimpleNamespace(origin="http://127.0.0.1:3015")
    handler.headers = {}
    handler.send_response = lambda _: None
    handler.send_header = lambda *_: None

    def abort(*_):
        raise ConnectionAbortedError("Windows client closed the socket")

    handler.end_headers = abort if stage == "headers" else lambda: None
    handler.wfile = SimpleNamespace(write=abort)
    handler.respond(200, {"ok": True})


def test_expired_preview_is_distinct_from_an_invalid_session_key(service):
    headers = {"Origin": service.origin, "X-Sphere-Preview": "1", "Content-Type": "application/json"}
    body = json.dumps({"device_id": "414ce0e9-4b93-4f96-b9ca-ee675f53835e"}).encode()
    _, session = post(service, headers, body=body)
    service.session["born"] -= MAX_SESSION_SECONDS + 1
    status, data = post(service, {**headers, "X-Scene-Session": session["id"], "X-Scene-Key": session["key"]}, path="/frame?sequence=1")
    assert status == 410 and data["error"] == "preview_expired"
    assert service.session is None
