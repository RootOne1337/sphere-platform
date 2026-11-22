"""Reviewed XFeat attachment for a single controlled vehicle route."""

import hashlib
import json
import math
import re
from pathlib import Path

from motor_worker import route_xfeat


REVIEW = "xfeat-vehicle.json"
PROOF = "xfeat-vehicle-replay.json"
MODEL = "route-xfeat.onnx"
SCHEMA = "sphere-route-xfeat-controlled-vehicle-v1"
PROOF_SCHEMA = "sphere-route-xfeat-replay-v1"
POLICY = route_xfeat.XFEAT_POLICY
_RUNTIME = Path(route_xfeat.__file__)
RUNTIME_SHA256 = hashlib.sha256(_RUNTIME.read_bytes()).hexdigest()


def _read(path, limit):
    if not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("route_xfeat_attachment_quota")
    return path.read_bytes()


def validate_replay(proof, receipt):
    if (type(proof) is not dict or proof.get("schema") != PROOF_SCHEMA
            or proof.get("route_sha256") != receipt["sha256"]
            or proof.get("cache_sha256") != receipt["cache_sha256"]
            or proof.get("runtime_sha256") != RUNTIME_SHA256
            or proof.get("model_sha256") != route_xfeat.MODEL_SHA256
            or type(proof.get("physical_actions")) is not int or proof["physical_actions"] != 0
            or proof.get("transport") != "isolated_vehicle_http_jpeg"):
        raise ValueError("route_xfeat_replay_binding")
    positive, negative = proof.get("independent_route"), proof.get("unrelated_route")
    if (type(positive) is not dict or type(negative) is not dict
            or type(positive.get("observations")) is not int or positive["observations"] < 10
            or type(positive.get("timely_throttle")) is not int
            or not 0 < positive["timely_throttle"] <= positive["observations"]
            or type(positive.get("p95_receiver_ms")) not in (int, float)
            or not math.isfinite(positive["p95_receiver_ms"])
            or not 0 <= positive["p95_receiver_ms"] <= 250
            or type(negative.get("observations")) is not int or negative["observations"] < 10
            or type(negative.get("verified_poses")) is not int or negative["verified_poses"] != 0):
        raise ValueError("route_xfeat_replay_unqualified")

    captures = (receipt["source_capture_sha256"], positive.get("capture_sha256"),
                negative.get("capture_sha256"))
    if (any(type(sha) is not str or not re.fullmatch(r"[0-9a-f]{64}", sha) for sha in captures)
            or len(set(captures)) != 3):
        raise ValueError("route_xfeat_replay_capture_binding")


def load_vehicle_xfeat(folder, receipt, *, stamp):
    review = folder / REVIEW
    if not review.exists() and not review.is_symlink():
        return None, (), None
    paths = review, folder / PROOF, folder / MODEL, _RUNTIME
    before = stamp(paths)
    doc = json.loads(_read(review, 8192))
    proof = _read(paths[1], 512 * 1024)
    model = _read(paths[2], 4 * 1024**2)
    expected = dict(schema=SCHEMA, policy=POLICY, scope="controlled_experimental_vehicle",
                    route_sha256=receipt["sha256"], cache_sha256=receipt["cache_sha256"],
                    geometry_sha256=receipt["geometry_sha256"], source_capture_sha256=receipt["source_capture_sha256"],
                    runtime_sha256=RUNTIME_SHA256, model_sha256=route_xfeat.MODEL_SHA256,
                    proof_sha256=hashlib.sha256(proof).hexdigest())
    if (type(doc) is not dict or doc != expected
            or hashlib.sha256(_read(_RUNTIME, 128 * 1024)).hexdigest() != RUNTIME_SHA256
            or hashlib.sha256(model).hexdigest() != route_xfeat.MODEL_SHA256):
        raise ValueError("route_xfeat_attachment_invalid")
    validate_replay(json.loads(proof), receipt)
    if stamp(paths) != before:
        raise ValueError("route_xfeat_attachment_changed")
    return model, paths, before
