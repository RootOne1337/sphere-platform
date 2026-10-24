"""Preview geometry and request-boundary tests; no GPU, download or Android."""
import json
import threading
from http.client import HTTPConnection

import numpy as np
import pytest

from scripts.pilot.teaching_scene import Handler, PreviewServer, unproject


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
        status, data = post(service, {"Origin": service.origin, "X-Sphere-Preview": "1"})
        assert status == 409 and data["error"] == "busy_no_queue"
    finally:
        service.lock.release()
