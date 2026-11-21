"""Offline replay must use the exact query, never a reference or invented line."""

import copy
from types import SimpleNamespace

import pytest

from scripts.pilot.render_offline_route_check import validated_samples


def evidence():
    route = SimpleNamespace(id="route", source_capture_sha256="a" * 64, source_frame_indices=(2, 5))
    sample = {
        "source_index": 3,
        "media_seconds": 0.2,
        "pose": {
            "route_id": "route",
            "receiver_sequence": 4,
            "state": "localized",
            "source_rgb_sha256": "b" * 64,
            "polyline_px": [[10.0, 20.0], [30.0, 40.0]],
        },
    }
    report = {
        "schema": "sphere-route-localization-quality-v1",
        "route_id": "route",
        "capture_manifest_sha256": "a" * 64,
        "offline_media_clock": True,
        "physical_actions": 0,
        "execution_qualified": False,
        "samples": [sample],
    }
    return route, report


def test_query_binding_accepts_heldout_frame():
    route, report = evidence()
    assert list(validated_samples(report, route, "a" * 64)) == [3]


@pytest.mark.parametrize(
    "mutation", ["reference", "sequence", "unknown_line", "bad_time", "wrong_capture"]
)
def test_bad_binding_is_rejected(mutation):
    route, report = evidence()
    report = copy.deepcopy(report)
    sample = report["samples"][0]
    if mutation == "reference":
        sample["source_index"], sample["pose"]["receiver_sequence"] = 2, 3
    elif mutation == "sequence":
        sample["pose"]["receiver_sequence"] = 2
    elif mutation == "unknown_line":
        sample["pose"]["state"] = "unknown"
    elif mutation == "bad_time":
        sample["media_seconds"] = float("nan")
    else:
        report["capture_manifest_sha256"] = "c" * 64
    with pytest.raises(ValueError):
        validated_samples(report, route, "a" * 64)
