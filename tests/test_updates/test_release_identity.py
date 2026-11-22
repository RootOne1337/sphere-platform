"""Publication and read boundaries for deterministic Android update offers."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import backend.api.v1.updates.router as updates

VALID = {
    "platform": "android", "flavor": "dev", "version_code": 10241,
    "version_name": "1.2.41-dev", "download_url": "https://cdn.example.test/agent.apk",
    "sha256": "a" * 64, "mandatory": False, "changelog": None,
}


@pytest.mark.parametrize("change", [
    {"sha256": ""}, {"sha256": "A" * 64}, {"sha256": "0" * 63},
    {"platform": "andriod"}, {"flavor": "deev"}, {"version_name": "   "},
    {"version_code": True}, {"version_code": "10241"}, {"mandatory": "false"},
    {"download_url": "https://"}, {"download_url": "https://user:secret@cdn.example.test/a.apk"},
    {"download_url": "https://cdn.example.test/a.apk#fragment"},
    {"download_url": "https://cdn.example.test:99999/a.apk"},
    {"download_url": "https://cdn.example.test/a apk"}, {"unknown": "ignored?"},
])
def test_invalid_publication_metadata_is_rejected(change):
    with pytest.raises(ValidationError):
        updates.CreateReleaseRequest.model_validate({**VALID, **change})


def test_valid_managed_url_and_signed_external_url_are_preserved():
    for url in (
        "/api/v1/updates/artifacts/" + "a" * 64,
        "https://cdn.example.test/a.apk?signature=abc%2Bdef&expires=123",
    ):
        request = updates.CreateReleaseRequest.model_validate({**VALID, "download_url": url})
        assert request.download_url == url


def test_same_channel_version_cannot_be_replaced_or_republished(tmp_path, monkeypatch):
    path = tmp_path / "releases.json"
    monkeypatch.setattr(updates, "_UPDATES_PATH", path)
    first = asyncio.run(updates.create_release(updates.CreateReleaseRequest(**VALID)))
    persisted = path.read_bytes()
    for change in ({}, {"sha256": "b" * 64}, {"version_name": "different"}):
        with pytest.raises(HTTPException) as failure:
            asyncio.run(updates.create_release(updates.CreateReleaseRequest(**{**VALID, **change})))
        assert failure.value.status_code == 409
        assert path.read_bytes() == persisted
    assert json.loads(first.body)["sha256"] == VALID["sha256"]


def test_same_version_in_independent_canary_and_flavor_channels_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(updates, "_UPDATES_PATH", tmp_path / "releases.json")
    for change in ({}, {"platform": "android-canary"}, {"flavor": "enterprise"}):
        response = asyncio.run(updates.create_release(updates.CreateReleaseRequest(**{**VALID, **change})))
        assert response.status_code == 201
    assert len(updates._load_releases()) == 3


def test_legacy_conflicting_latest_version_fails_closed():
    with pytest.raises(HTTPException) as failure:
        updates._latest_release([VALID, {**VALID, "sha256": "b" * 64}])
    assert failure.value.status_code == 503


def test_identical_legacy_duplicates_and_retired_conflicts_do_not_mask_newer_version():
    releases = [{**VALID, "version_code": 10240}, {**VALID, "version_code": 10240, "sha256": "b" * 64},
                {**VALID, "id": "first"}, {**VALID, "id": "second"}]
    assert updates._latest_release(releases)["id"] == "first"
