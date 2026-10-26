"""One isolated denser SfM trial using existing pinned local tools. No GS training.

Keeps an explicit fixed held-out set out of preparation. No source model is
overwritten, download performed, service job adopted or navigation authorized.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path

from motor_worker.browser_teach import prepare_browser, validate_browser
from scripts.pilot.learned_route_features import extract_and_match
from scripts.pilot.reconstruct_route import ROOT, TOOLS, model_geometry
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_motion_audit import audit


def run(capture_path, baseline_path, heldout_path, output):
    if output.exists():
        raise ValueError("sfm_trial_output_exists")
    source = baseline_path.read_bytes()
    baseline = json.loads(source)
    heldout = json.loads(heldout_path.read_bytes())
    capture = validate_browser(capture_path)
    source_sha = hashlib.sha256(capture.originals["manifest.json"]).hexdigest()
    if (
        baseline["source_manifest_sha256"] != source_sha
        or heldout["source_manifest_sha256"] != source_sha
        or heldout.get("same_capture") is not True
    ):
        raise ValueError("sfm_trial_source_binding")
    excluded = frozenset(row["source_index"] for row in heldout["views"])
    if not 1 <= len(excluded) <= 100:
        raise ValueError("sfm_trial_heldout_budget")

    def check():
        if (output / "CANCEL").exists():
            raise RuntimeError("cancelled")
        if evaluate(collect(ROOT), min_ram_gib=12):
            raise RuntimeError("sfm_trial_resource_guard")

    check()
    output.mkdir(parents=True)
    sys.path.insert(0, str(TOOLS / "pycolmap-4.2.1"))
    import pycolmap as p

    if p.__version__ != "4.2.1":
        raise ValueError("sfm_trial_pycolmap_version")
    token = p.CancellationToken()
    done = threading.Event()
    aborted = []
    started = time.monotonic()

    def watchdog():
        while not done.wait(3):
            try:
                check()
                if time.monotonic() - started > 900:
                    raise RuntimeError("sfm_trial_timeout")
            except RuntimeError as error:
                aborted.append(str(error))
                token.cancel()
                return

    thread = threading.Thread(target=watchdog, daemon=True)
    thread.start()
    try:
        prepared = output / "prepared"
        prepare_browser(
            capture_path,
            prepared,
            interval=0.25,
            max_images=240,
            max_bytes=2**31,
            excluded_indices=excluded,
        )
        check()
        intrinsics = baseline["cameras"][0]["intrinsics"]
        reader = p.ImageReaderOptions(
            camera_model="PINHOLE",
            camera_params=",".join(str(intrinsics[k]) for k in ("fx", "fy", "cx", "cy")),
        )
        database = prepared / "database.db"
        features = extract_and_match(ROOT, prepared, database, reader, token, check)
        check()
        models_path = prepared / "models"
        models_path.mkdir()
        options = p.IncrementalPipelineOptions(
            num_threads=4,
            random_seed=17,
            max_runtime_seconds=600,
            max_num_models=4,
            structure_less_registration_fallback=False,
            ba_refine_sensor_from_rig=False,
            ba_refine_focal_length=False,
            ba_refine_principal_point=False,
            ba_refine_extra_params=False,
        )
        models = p.incremental_mapping(
            database, prepared / "images", models_path, options=options, cancellation_token=token
        )
        if aborted:
            raise RuntimeError(aborted[0])
        if not models:
            raise RuntimeError("sfm_trial_no_model")
        model = max(models.values(), key=lambda m: m.num_reg_images())
        geometry = model_geometry(model, prepared)
        selected = json.loads((prepared / "reconstruction-input.json").read_bytes())["images"]
        assert not {r["source_index"] for r in selected} & excluded
        (output / "geometry.json").write_text(json.dumps(geometry, indent=2) + "\n")
        report = dict(
            scope="DENSER_FIXED_INTRINSICS_SFM_TRIAL_NOT_NAVIGATION",
            sourceManifestSha256=source_sha,
            baselineGeometrySha256=hashlib.sha256(source).hexdigest(),
            heldoutSourceIndices=sorted(excluded),
            preparedViews=len(selected),
            registeredViews=model.num_reg_images(),
            components=len(models),
            points=model.num_points3D(),
            meanReprojectionPx=model.compute_mean_reprojection_error(),
            features=features,
            intrinsicsFixedToBaselineEstimate=True,
            groundTruthIntrinsics=False,
            temporal=audit(geometry),
            gaussianTraining=False,
            sourceOverwritten=False,
            physicalActions=0,
            elapsedSeconds=time.monotonic() - started,
            executionQualified=False,
        )
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        done.set()
        thread.join(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "baseline", "heldout", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    os.environ.update(OMP_NUM_THREADS="4", HF_HUB_OFFLINE="1")
    print(json.dumps(run(args.capture, args.baseline, args.heldout, args.output)))


if __name__ == "__main__":
    main()
