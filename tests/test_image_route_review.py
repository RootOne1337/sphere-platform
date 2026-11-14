import hashlib
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from scripts.pilot.image_route_review import read_image_route_review
from scripts.pilot.reconstruction_service import Jobs, handler


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(job):
    (job / "input").mkdir(parents=True)
    frames = (
        b"\n".join(
            json.dumps(dict(index=i, relative_ticks_90k=i * 3000)).encode() for i in range(4)
        )
        + b"\n"
    )
    (job / "input/frames.jsonl").write_bytes(frames)
    manifest = json.dumps({"files": {"frames.jsonl": {"sha256": sha(frames)}}}).encode()
    (job / "input/manifest.json").write_bytes(manifest)
    folder = job / "image-route-review"
    folder.mkdir()
    data = dict(
        schema="sphere-image-route-review-v1",
        scope="OFFLINE_SAME_RECORDING",
        source_manifest_sha256=sha(manifest),
        position_confirmed=False,
        arrival_confirmed=False,
        execution_qualified=False,
        reference_ticks_90k=[0, 9000],
        samples=[
            dict(
                source_index=1,
                ticks_90k=3000,
                raw_reference_ticks_90k=0,
                raw_score=0.8,
                sequence_reference_ticks_90k=0,
                sequence_status="reference_selected",
                sequence_score=0.7,
            ),
            dict(
                source_index=2,
                ticks_90k=6000,
                raw_reference_ticks_90k=9000,
                raw_score=0.5,
                sequence_reference_ticks_90k=None,
                sequence_status="ambiguous",
            ),
        ],
    )

    def publish(value, **receipt_overrides):
        body = json.dumps(value).encode()
        (folder / "review.json").write_bytes(body)
        receipt = dict(
            schema="sphere-image-route-review-receipt-v1",
            scope="DIAGNOSTIC_ONLY",
            execution_qualified=False,
            source_manifest_sha256=sha(manifest),
            review_sha256=sha(body),
            frames_sha256=sha(frames),
        )
        receipt.update(receipt_overrides)
        (folder / "receipt.json").write_text(json.dumps(receipt), encoding="utf8")
        return body

    return data, publish


def test_valid_review_has_exact_source_binding(tmp_path):
    data, publish = fixture(tmp_path)
    body = publish(data)
    assert read_image_route_review(tmp_path) == body


@pytest.mark.parametrize(
    "case",
    [
        "manifest",
        "frames",
        "tick",
        "index",
        "duplicate",
        "outside_ref",
        "nonfinite",
        "qualified",
        "extra",
        "bad_status",
        "score",
        "receipt",
        "cross_job",
    ],
)
def test_invalid_review_never_returned(tmp_path, case):
    job = tmp_path / "a"
    data, publish = fixture(job)
    if case == "tick":
        data["samples"][0]["ticks_90k"] = 3001
    if case == "index":
        data["samples"][0]["source_index"] = 4
    if case == "duplicate":
        data["samples"].append(dict(data["samples"][0]))
    if case == "outside_ref":
        data["reference_ticks_90k"] = [0, 9999]
    if case == "nonfinite":
        data["samples"][0]["raw_score"] = float("nan")
    if case == "qualified":
        data["execution_qualified"] = True
    if case == "extra":
        data["samples"][0]["html"] = "<script>bad</script>"
    if case == "bad_status":
        data["samples"][0]["sequence_status"] = "ambiguous"
    if case == "score":
        data["samples"][0]["raw_score"] = True
    publish(data, **({"execution_qualified": True} if case == "receipt" else {}))
    if case == "manifest":
        (job / "input/manifest.json").write_bytes(b"{}")
    if case == "frames":
        (job / "input/frames.jsonl").write_bytes(b"{}\n")
    if case == "cross_job":
        other = tmp_path / "b"
        fixture(other)
        (other / "input/manifest.json").write_bytes(
            (other / "input/manifest.json").read_bytes() + b" "
        )
        import shutil

        shutil.copytree(
            job / "image-route-review", other / "image-route-review", dirs_exist_ok=True
        )
        job = other
    with pytest.raises(ValueError):
        read_image_route_review(job)


def test_oversized_and_symlink_artifacts_fail_closed(tmp_path):
    data, publish = fixture(tmp_path)
    publish(data)
    path = tmp_path / "image-route-review/review.json"
    path.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(ValueError, match="quota"):
        read_image_route_review(tmp_path)
    path.unlink()
    external = tmp_path / "external.json"
    external.write_bytes(b"{}")
    try:
        path.symlink_to(external)
    except OSError:
        pytest.skip("symlink unavailable")
    with pytest.raises(ValueError, match="path"):
        read_image_route_review(tmp_path)


def test_http_capability_and_missing_vs_partial(tmp_path):
    identity, key = "a" * 32, "b" * 64
    root = tmp_path / "jobs"
    root.mkdir()
    job = root / identity
    data, publish = fixture(job)
    body = publish(data)
    (job / "control.json").write_text(
        json.dumps({"key_sha256": sha(key.encode())}), encoding="utf8"
    )
    jobs = Jobs(root, tmp_path / "python.exe")
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(jobs, "http://127.0.0.1:3015", 0))
    port = server.server_address[1]
    server.RequestHandlerClass = handler(jobs, "http://127.0.0.1:3015", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def get(capability):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        c.request(
            "GET",
            f"/jobs/{identity}/image-route-review",
            headers={"X-Sphere-Reconstruction": "1", "X-Job-Key": capability},
        )
        r = c.getresponse()
        out = (r.status, r.read())
        c.close()
        return out

    def health():
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
        c.request("GET", "/health", headers={"X-Sphere-Reconstruction": "1"})
        r = c.getresponse()
        out = (r.status, json.loads(r.read()))
        c.close()
        return out

    try:
        status, state = health()
        assert status == 200 and state["live_session_active"] is False
        assert state["image_route_review_contract"] == "source_bound_offline_v1"
        jobs.navigation.clock = lambda: 10.0
        active = {"deadline": 11.0, "id": "private-session"}
        jobs.navigation.live = active
        state = health()[1]
        assert state["live_session_active"] is True and "id" not in state
        jobs.navigation.clock = lambda: 12.0
        assert health()[1]["live_session_active"] is False
        assert jobs.navigation.live is active  # health must not expire or archive it
        jobs.navigation.live = None
        assert get("wrong")[0] == 403
        assert get(key) == (200, body)
        (job / "image-route-review/receipt.json").unlink()
        assert get(key)[0] == 409
        (job / "image-route-review/review.json").unlink()
        (job / "image-route-review").rmdir()
        status, response = get(key)
        assert status == 404 and json.loads(response)["error"] == "image_route_review_not_found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
