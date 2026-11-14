"""Load a reviewed native descriptor attachment for one prepared route."""

import hashlib
import json
import re
from pathlib import Path

from motor_worker import route_descriptor_recovery as recovery
from motor_worker.route_localization import SparseRoute


SCHEMA = "sphere-route-descriptor-recovery-v1"
REVIEW = "descriptor-recovery.json"
DESCRIPTORS = "descriptor-route.json"
_RUNTIME = Path(recovery.__file__)
_IMPORTED_RUNTIME_SHA256 = hashlib.sha256(_RUNTIME.read_bytes()).hexdigest()
DESCRIPTOR_RECOVERY_POLICY = recovery.DESCRIPTOR_RECOVERY_POLICY


def load_descriptor_recovery(folder, receipt, *, stamp):
    review = folder / REVIEW
    if not review.exists() and not review.is_symlink():
        return None, (), None

    descriptor = folder / DESCRIPTORS
    paths = (review, descriptor, _RUNTIME)
    initial_stamp = stamp(paths)
    if not review.is_file() or not 0 < review.stat().st_size <= 8192:
        raise ValueError("route_descriptor_recovery_review_quota")
    if not descriptor.is_file() or not 0 < descriptor.stat().st_size <= 8 * 1024**2:
        raise ValueError("route_descriptor_recovery_asset_quota")
    document = json.loads(review.read_bytes())
    binding_fields = (
        "sha256", "cache_sha256", "pipeline_sha256", "geometry_sha256",
        "source_capture_sha256", "source_index_sha256", "model_sha256",
    )
    expected_binding = {key: receipt[key] for key in binding_fields}
    if (
        type(document) is not dict
        or document.keys() != {"schema", "scope", "reviewed", "policy", "runtime_sha256",
                               "binding", "descriptor_sha256", "source_proof_sha256", "replay_proof_sha256"}
        or document["schema"] != SCHEMA
        or document["scope"] != "observation_only"
        or document["reviewed"] is not True
        or document["policy"] != recovery.DESCRIPTOR_RECOVERY_POLICY
        or document["binding"] != expected_binding
        or document["runtime_sha256"] != _IMPORTED_RUNTIME_SHA256
        or _IMPORTED_RUNTIME_SHA256 != hashlib.sha256(_RUNTIME.read_bytes()).hexdigest()
        or any(type(document[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", document[key])
               for key in ("descriptor_sha256", "source_proof_sha256", "replay_proof_sha256"))
    ):
        raise ValueError("route_descriptor_recovery_review_invalid")
    sidecar = SparseRoute.load(descriptor, sha256=document["descriptor_sha256"])
    if stamp(paths) != initial_stamp:
        raise ValueError("route_descriptor_recovery_changed")
    return sidecar, paths, initial_stamp
