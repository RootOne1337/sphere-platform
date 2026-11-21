"""Controlled learned recovery must remain bound to measured route and replay assets."""

import hashlib
import json

import pytest

from scripts.pilot import route_xfeat_attachment as attachment
from scripts.pilot.route_workspace import RouteWorkspaces


def evidence(receipt, model_sha):
    return dict(schema=attachment.PROOF_SCHEMA, route_sha256=receipt["sha256"],
                cache_sha256=receipt["cache_sha256"], runtime_sha256=attachment.RUNTIME_SHA256,
                model_sha256=model_sha, transport="isolated_vehicle_http_jpeg", physical_actions=0,
                independent_route=dict(observations=30, timely_throttle=8,
                                       p95_receiver_ms=218., capture_sha256="4" * 64),
                unrelated_route=dict(observations=40, verified_poses=0, capture_sha256="5" * 64))


def test_review_refuses_a_changed_model_and_rechecks_source(tmp_path, monkeypatch):
    model = b"test-only model"
    model_sha = hashlib.sha256(model).hexdigest()
    receipt = dict(sha256="1" * 64, cache_sha256="2" * 64, geometry_sha256="3" * 64,
                   source_capture_sha256="6" * 64)
    monkeypatch.setattr(attachment.route_xfeat, "MODEL_SHA256", model_sha)
    stamp = RouteWorkspaces._runtime_source_stamp
    assert attachment.load_vehicle_xfeat(tmp_path, receipt, stamp=stamp) == (None, (), None)
    proof = json.dumps(evidence(receipt, model_sha)).encode()
    (tmp_path / attachment.PROOF).write_bytes(proof)
    (tmp_path / attachment.MODEL).write_bytes(model)
    review = dict(schema=attachment.SCHEMA, policy=attachment.POLICY, scope="controlled_experimental_vehicle",
                  route_sha256=receipt["sha256"], cache_sha256=receipt["cache_sha256"],
                  geometry_sha256=receipt["geometry_sha256"], source_capture_sha256=receipt["source_capture_sha256"],
                  runtime_sha256=attachment.RUNTIME_SHA256, model_sha256=model_sha,
                  proof_sha256=hashlib.sha256(proof).hexdigest())
    (tmp_path / attachment.REVIEW).write_text(json.dumps(review), encoding="utf-8")
    loaded, paths, bound = attachment.load_vehicle_xfeat(tmp_path, receipt, stamp=stamp)
    assert loaded == model
    assert len(paths) == 4 and bound == stamp(paths)
    with pytest.raises(ValueError, match="attachment_invalid"):
        attachment.load_vehicle_xfeat(tmp_path, dict(receipt, geometry_sha256="0" * 64), stamp=stamp)
    (tmp_path / attachment.MODEL).write_bytes(b"changed")
    with pytest.raises(ValueError, match="attachment_invalid"):
        attachment.load_vehicle_xfeat(tmp_path, receipt, stamp=stamp)


@pytest.mark.parametrize(("side", "change"), [
    ("independent_route", {"timely_throttle": 0}),
    ("independent_route", {"p95_receiver_ms": 250.1}),
    ("independent_route", {"capture_sha256": "6" * 64}),
    ("unrelated_route", {"verified_poses": 1}),
    ("unrelated_route", {"capture_sha256": "4" * 64}),
])
def test_review_needs_timely_independent_command_and_zero_unrelated_poses(side, change):
    receipt = dict(sha256="1" * 64, cache_sha256="2" * 64, source_capture_sha256="6" * 64)
    row = evidence(receipt, attachment.route_xfeat.MODEL_SHA256)
    attachment.validate_replay(row, receipt)
    row[side].update(change)
    with pytest.raises(ValueError, match="route_xfeat_replay"):
        attachment.validate_replay(row, receipt)
