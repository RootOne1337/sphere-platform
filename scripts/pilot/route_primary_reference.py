"""Publish the verified primary geometry as a Reference-LK preparation source."""

import hashlib
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.pilot.atomic_json import write_json
from scripts.pilot.route_preparation_source import MODEL_FILES, SCHEMA, resolve_alternative_source
from scripts.pilot.sparse_scene_receipt import verify_sparse_receipt


PRIMARY_NATIVE_ID = "primary-native"


def _digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish_primary_reference_source(job):
    """Reuse admitted camera poses and measured observations from this capture."""
    job = Path(job).resolve(strict=True)
    evidence = verify_sparse_receipt(job)
    hashes = evidence["files"]
    assessment = json.loads((job / "quality.json").read_bytes()).get("selection") or {}
    coverage = assessment.get("source_coverage") or {}
    if (assessment.get("route_admissible") is not True or assessment.get("scene_admissible") is not True
            or coverage.get("endpoints_observed") is not True or coverage.get("all_intervals_observed") is not True):
        raise ValueError("route_alternative_geometry_not_admitted")

    model = job / "prepared/sparse/0"
    expected = {name: hashes.get(f"prepared/sparse/0/{name}") for name in MODEL_FILES}
    if any(sha is None for sha in expected.values()):
        raise ValueError("route_alternative_native_layout")
    root = job / "alternatives"
    root.mkdir(exist_ok=True)
    if root.resolve(strict=True).parent != job or root.is_symlink() or root.is_junction():
        raise ValueError("alternative_geometry_path")
    target = root / PRIMARY_NATIVE_ID
    if not target.exists():
        with TemporaryDirectory(prefix=".native-route-", dir=job) as scratch:
            stage = Path(scratch).resolve(strict=True)
            if stage.parent != job:
                raise ValueError("alternative_geometry_path")
            bundle = stage / PRIMARY_NATIVE_ID
            native = bundle / "native"
            output = native / "model"
            output.mkdir(parents=True)
            shutil.copyfile(job / "geometry.json", bundle / "geometry.json")
            for name, sha in expected.items():
                shutil.copyfile(model / name, output / name)
                if _digest(output / name) != sha:
                    raise ValueError("route_alternative_native_changed")
            write_json(native / "assessment.json", assessment)
            write_json(native / "producer-proof.json", {
                "schema": "sphere-primary-measured-source-v1",
                "sparse_receipt_sha256": _digest(job / "sparse-receipt.json"),
                "source_manifest_sha256": hashes["input/manifest.json"],
                "geometry_sha256": hashes["geometry.json"],
                "execution_qualified": False,
            })
            write_json(bundle / "receipt.json", {
                "schema": "sphere-alternative-geometry-v1", "id": PRIMARY_NATIVE_ID,
                "scope": "DIAGNOSTIC_ONLY", "execution_qualified": False,
                "label": "Основная геометрия · проверка движения без HUD записи",
                "source_manifest_sha256": hashes["input/manifest.json"],
                "geometry_sha256": hashes["geometry.json"],
            })
            write_json(native / "source.json", {
                "schema": SCHEMA, "alternative_id": PRIMARY_NATIVE_ID, "scope": "READ_ONLY_ROUTE_ASSETS",
                "execution_qualified": False, "geometry_sha256": hashes["geometry.json"],
                "source_manifest_sha256": hashes["input/manifest.json"],
                "reconstruction_input_sha256": hashes["prepared/reconstruction-input.json"],
                "model_sha256": expected,
                "evidence_sha256": {name: _digest(native / name)
                                    for name in ("assessment.json", "producer-proof.json")},
            })
            if (_digest(bundle / "geometry.json") != hashes["geometry.json"]
                    or verify_sparse_receipt(job) != evidence):
                raise ValueError("route_preparation_source_changed")
            try:
                bundle.rename(target)
            except FileExistsError:
                pass  # An identical published source is checked below.
    selection = resolve_alternative_source(job, PRIMARY_NATIVE_ID)["binding"]
    if (selection["geometry_sha256"] != hashes["geometry.json"]
            or selection["source_manifest_sha256"] != hashes["input/manifest.json"]
            or selection["model_sha256"] != expected):
        raise ValueError("route_preparation_source_changed")
    pointer = job / "alternative-selection.json"
    if not pointer.exists() and not pointer.is_symlink():
        suggested = {"schema": "sphere-alternative-selection-v1", "id": PRIMARY_NATIVE_ID,
                     "scope": "DIAGNOSTIC_ONLY", "execution_qualified": False,
                     "source_manifest_sha256": hashes["input/manifest.json"], "geometry_sha256": hashes["geometry.json"]}
        # Publish complete bytes before making a recommendation for this job.
        try:
            with pointer.open("x", encoding="utf-8") as output:
                json.dump(suggested, output, separators=(",", ":"))
        except FileExistsError:
            pass
    return PRIMARY_NATIVE_ID
