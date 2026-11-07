"""Lifecycle tests for the optional image index, without running game input."""

import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from scripts.pilot import image_route_workspace as workspace


def source(job):
    (job / "input").mkdir()
    frames = b'{"index":0,"relative_ticks_90k":0}\n{"index":1,"relative_ticks_90k":90000}\n'
    (job / "input/frames.jsonl").write_bytes(frames)
    manifest = json.dumps(
        {"files": {"frames.jsonl": {"sha256": hashlib.sha256(frames).hexdigest()}}}
    ).encode()
    (job / "input/manifest.json").write_bytes(manifest)
    return manifest


def publish(job):
    folder = job / "image-route-review"
    folder.mkdir()
    manifest_sha = hashlib.sha256((job / "input/manifest.json").read_bytes()).hexdigest()
    body = json.dumps(
        dict(
            schema="sphere-image-route-review-v1",
            scope="OFFLINE_SAME_RECORDING",
            source_manifest_sha256=manifest_sha,
            position_confirmed=False,
            arrival_confirmed=False,
            execution_qualified=False,
            reference_ticks_90k=[0, 90000],
            samples=[
                dict(
                    source_index=0,
                    ticks_90k=0,
                    raw_reference_ticks_90k=None,
                    raw_score=0,
                    sequence_reference_ticks_90k=None,
                    sequence_status="unknown",
                )
            ],
        )
    ).encode()
    (folder / "review.json").write_bytes(body)
    (folder / "receipt.json").write_text(
        json.dumps(
            dict(
                schema="sphere-image-route-review-receipt-v1",
                scope="DIAGNOSTIC_ONLY",
                execution_qualified=False,
                source_manifest_sha256=manifest_sha,
                review_sha256=hashlib.sha256(body).hexdigest(),
            )
        ),
        encoding="utf8",
    )


def test_valid_previous_review_is_not_rewritten_or_restarted(tmp_path, monkeypatch):
    source(tmp_path)
    publish(tmp_path)
    before = {p.name: p.read_bytes() for p in (tmp_path / "image-route-review").iterdir()}
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("must reuse, not launch"))
    result = workspace.run_optional(tmp_path, "none")
    assert result == dict(phase="ready", reused=True, execution_qualified=False)
    assert before == {p.name: p.read_bytes() for p in (tmp_path / "image-route-review").iterdir()}
    assert not (tmp_path / "image-route-workspace").exists()


def test_invalid_previous_review_and_interrupted_intent_never_start_again(tmp_path, monkeypatch):
    source(tmp_path)
    (tmp_path / "image-route-review").mkdir()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no implicit retry"))
    assert (
        workspace.run_optional(tmp_path, "game")["error"] == "image_route_existing_review_invalid"
    )
    (tmp_path / "image-route-review").rmdir()
    folder = tmp_path / "image-route-workspace"
    folder.mkdir()
    (folder / "state.json").write_text('{"phase":"running"}')
    workspace.settle_interrupted(tmp_path)
    assert (folder / "CANCEL").exists()
    assert (tmp_path / "CANCEL").exists()
    assert workspace.run_optional(tmp_path, "game")["error"] == "image_route_service_restarted"


def test_missing_cpu_runtime_is_optional_and_source_unchanged(tmp_path):
    raw = source(tmp_path)
    result = workspace.run_optional(tmp_path, "avatar", python=tmp_path / "absent.exe")
    assert result["phase"] == "unavailable" and result["execution_qualified"] is False
    assert (tmp_path / "input/manifest.json").read_bytes() == raw
    assert not (tmp_path / "state.json").exists()


def test_owned_child_result_must_be_valid_before_ready(tmp_path, monkeypatch):
    source(tmp_path)
    calls = []

    class Child:
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            publish(tmp_path)
            self.returncode = 0

    child = Child()

    def spawn(command, **kwargs):
        calls.append(command)
        assert kwargs["stdin"] == subprocess.DEVNULL and kwargs["cwd"] == workspace.ROOT
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    assert workspace.run_optional(tmp_path, "none", python=sys.executable)["phase"] == "ready"
    assert calls == [
        [
            sys.executable,
            "-m",
            "scripts.pilot.image_route_builder",
            "--job",
            str(tmp_path),
            "--mask",
            "none",
        ]
    ]
    assert not (tmp_path / "state.json").exists()


def test_caller_guard_stops_only_owned_child_and_preserves_original_failure(tmp_path, monkeypatch):
    source(tmp_path)
    checks = []
    actions = []

    class Child:
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            actions.append(("wait", timeout))
            assert (tmp_path / "image-route-workspace/CANCEL").exists()
            self.returncode = 1

        def terminate(self):
            pytest.fail("cooperative exit expected")

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Child())

    def guard():
        checks.append(1)
        if len(checks) > 1:
            raise RuntimeError("resource_guard")

    with pytest.raises(RuntimeError, match="resource_guard"):
        workspace.run_optional(tmp_path, "game", python=sys.executable, check=guard)
    assert actions == [("wait", 3)]
    assert workspace.read_status(tmp_path)["phase"] == "failed"
    assert not (tmp_path / "CANCEL").exists()


def test_spawn_failure_is_optional_not_a_false_success(tmp_path, monkeypatch):
    source(tmp_path)

    def fail(*a, **k):
        raise OSError("private host detail")

    monkeypatch.setattr(subprocess, "Popen", fail)
    result = workspace.run_optional(tmp_path, "none", python=sys.executable)
    assert result["phase"] == "failed" and "private" not in json.dumps(result)


def test_restart_between_child_exit_and_parent_settlement_cannot_report_ready(
    tmp_path, monkeypatch
):
    source(tmp_path)

    class Child:
        returncode = None

        def poll(self):
            return self.returncode

        def wait(self, timeout):
            publish(tmp_path)
            workspace.settle_interrupted(tmp_path)
            self.returncode = 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: Child())
    assert workspace.run_optional(tmp_path, "none", python=sys.executable)["phase"] == "cancelled"


def test_service_restart_cooperatively_releases_a_real_owned_child(tmp_path, monkeypatch):
    source(tmp_path)
    created = []
    actual_popen = subprocess.Popen
    child_code = (
        "import pathlib,time; p=pathlib.Path(" + repr(str(tmp_path)) + "); "
        "(p/'child-started').touch(); deadline=time.monotonic()+5\n"
        "while not (p/'image-route-workspace/CANCEL').exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        "(p/'child-exited').touch()"
    )

    def owned_child(command, **kwargs):
        assert command[1:3] == ["-m", "scripts.pilot.image_route_builder"]
        process = actual_popen([sys.executable, "-c", child_code], **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", owned_child)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(workspace.run_optional, tmp_path, "none", python=sys.executable)
        deadline = time.monotonic() + 5
        while not (tmp_path / "child-started").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (tmp_path / "child-started").exists()
        workspace.settle_interrupted(tmp_path)
        result = future.result(timeout=8)
    assert result["phase"] == "cancelled"
    assert len(created) == 1 and created[0].poll() is not None
    assert (tmp_path / "child-exited").exists() and (tmp_path / "CANCEL").exists()
    assert not (tmp_path / "image-route-review").exists()


def test_image_review_precedes_sfm_and_survives_its_refusal(tmp_path, monkeypatch):
    from scripts.pilot import reconstruct_route as route
    from scripts.pilot import route_hud_workspace as hud

    source(tmp_path)
    calls = []
    monkeypatch.setattr(route, "checkpoint", lambda _: None)
    monkeypatch.setattr(route, "make_observation_checkpoint", lambda _: lambda: None)
    from types import SimpleNamespace

    monkeypatch.setattr(route, "validate_browser", lambda _: SimpleNamespace(
        frames=[dict(relative_ticks_90k=5*90000)]))
    monkeypatch.setattr(route, "_prepare_vehicle_speed_reference", lambda *args: False)

    def prepare(job, mask, **kwargs):
        calls.append("index")
        publish(job)

    monkeypatch.setattr(workspace, "run_optional", prepare)
    monkeypatch.setattr(hud, "start", lambda *args: None)

    def fail(*a, **k):
        calls.append("sfm")
        raise RuntimeError("camera_geometry_degenerate")

    monkeypatch.setattr(route, "_reconstruct", fail)
    with pytest.raises(RuntimeError, match="camera_geometry_degenerate"):
        route.reconstruct(tmp_path, "none", 30000, route_only=True)
    assert calls == ["index", "sfm"]
    from scripts.pilot.image_route_review import read_image_route_review

    assert read_image_route_review(tmp_path)
