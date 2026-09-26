"""Cross-process regression tests for the file-backed OTA release catalog."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import time
from pathlib import Path

import pytest


def _mutate_release_process(
    catalog_path: str,
    start_event,
    ready_queue,
    result_queue,
    version_code: int,
    operation: str = "create",
    release_id: str | None = None,
) -> None:
    """Call a release mutation handler used by Gunicorn in a fresh process."""
    import backend.api.v1.updates.router as updates_module

    updates_module._UPDATES_PATH = Path(catalog_path)
    load_releases = updates_module._load_releases

    def delayed_load() -> list[dict]:
        releases = load_releases()
        # Give a concurrently scheduled worker time to read the same old catalog.
        time.sleep(0.5)
        return releases

    updates_module._load_releases = delayed_load
    ready_queue.put("ready")
    if not start_event.wait(timeout=15):
        result_queue.put((version_code, "start timeout"))
        return

    try:
        if operation == "create":
            payload = updates_module.CreateReleaseRequest(
                platform="android",
                flavor="dev",
                version_code=version_code,
                version_name=f"1.2.{version_code}-dev",
                download_url=f"https://cdn.example.test/sphere-{version_code}.apk",
                sha256=f"{version_code:064x}",
            )
            response = asyncio.run(updates_module.create_release(payload))
        else:
            response = asyncio.run(updates_module.delete_release(release_id or ""))
        result_queue.put((version_code, response.status_code))
    except BaseException as exc:  # propagate child failures to the parent assertion
        result_queue.put((version_code, repr(exc)))


def test_parallel_release_publications_preserve_both_entries(tmp_path):
    """Concurrent API writes from separate server workers must not lose a release."""
    context = multiprocessing.get_context("spawn")
    catalog_path = tmp_path / "releases.json"
    start_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_mutate_release_process,
            args=(str(catalog_path), start_event, ready_queue, result_queue, version_code),
        )
        for version_code in (501, 502)
    ]

    try:
        for worker in workers:
            worker.start()
        assert [ready_queue.get(timeout=20) for _ in workers] == ["ready", "ready"]
        start_event.set()
        results = [result_queue.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(timeout=20)
            assert not worker.is_alive(), "release worker did not exit"
            assert worker.exitcode == 0

        assert sorted(result for _, result in results) == [201, 201]
        releases = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert {release["version_code"] for release in releases} == {501, 502}
    finally:
        start_event.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        ready_queue.close()
        result_queue.close()


def test_parallel_create_and_delete_do_not_overwrite_each_other(tmp_path):
    """Creation and removal share one serialized read-modify-write boundary."""
    context = multiprocessing.get_context("spawn")
    catalog_path = tmp_path / "releases.json"
    catalog_path.write_text(json.dumps([{"id": "retire-me", "version_code": 500}]))
    start_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_mutate_release_process,
            args=(str(catalog_path), start_event, ready_queue, result_queue, 503, "create"),
        ),
        context.Process(
            target=_mutate_release_process,
            args=(
                str(catalog_path),
                start_event,
                ready_queue,
                result_queue,
                500,
                "delete",
                "retire-me",
            ),
        ),
    ]

    try:
        for worker in workers:
            worker.start()
        assert [ready_queue.get(timeout=20) for _ in workers] == ["ready", "ready"]
        start_event.set()
        results = [result_queue.get(timeout=20) for _ in workers]
        for worker in workers:
            worker.join(timeout=20)
            assert not worker.is_alive(), "release worker did not exit"
            assert worker.exitcode == 0

        assert sorted(result for _, result in results) == [201, 204]
        releases = json.loads(catalog_path.read_text(encoding="utf-8"))
        assert "retire-me" not in {release["id"] for release in releases}
        assert {release["version_code"] for release in releases} == {503}
    finally:
        start_event.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        ready_queue.close()
        result_queue.close()


def test_failed_catalog_replace_keeps_previous_release_file(tmp_path, monkeypatch):
    import backend.api.v1.updates.router as updates_module

    catalog_path = tmp_path / "releases.json"
    monkeypatch.setattr(updates_module, "_UPDATES_PATH", catalog_path)
    original = [{"id": "previous", "version_code": 500}]
    updates_module._save_releases(original)

    def fail_replace(source, target):
        raise OSError("simulated atomic-replace failure")

    monkeypatch.setattr(updates_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic-replace failure"):
        updates_module._save_releases([{"id": "new", "version_code": 501}])

    assert updates_module._load_releases() == original
    assert list(tmp_path.glob(".releases.json.*.tmp")) == []


def test_invalid_catalog_fails_closed_instead_of_looking_empty(tmp_path, monkeypatch):
    from fastapi import HTTPException

    import backend.api.v1.updates.router as updates_module

    catalog_path = tmp_path / "releases.json"
    catalog_path.write_text('{"unexpected": "object"}', encoding="utf-8")
    monkeypatch.setattr(updates_module, "_UPDATES_PATH", catalog_path)

    with pytest.raises(HTTPException) as exc_info:
        updates_module._load_releases()

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "OTA release catalog is invalid"
