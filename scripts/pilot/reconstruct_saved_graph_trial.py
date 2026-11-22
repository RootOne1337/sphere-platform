"""Isolated, guarded CPU SfM trial from a saved graph; no network or controls.

This can hold an estimated focal length fixed; it is not a calibrated FOV.
No original DB, image, geometry or video is written. Holdout membership remains
the one in the saved prepared inputs; an independent replay is still required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import threading
import time
from pathlib import Path

from scripts.pilot.atomic_json import write_json
from scripts.pilot.reconstruct_route import ROOT, TOOLS, model_geometry
from scripts.pilot.resource_guard import collect, evaluate
from scripts.pilot.route_motion_audit import audit


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def verify_fixed_focal(cameras, expected):
    if not cameras or not math.isfinite(expected) or expected <= 0:
        raise ValueError("saved_graph_fixed_focal_invalid")
    if any(
        not math.isfinite(float(camera.params[0])) or abs(float(camera.params[0]) - expected) > 1e-5
        for camera in cameras
    ):
        raise RuntimeError("saved_graph_fixed_focal_not_preserved")


def run(
    source,
    output,
    *,
    from_seconds=0.0,
    optimize_focal=False,
    spatial_filter=None,
    max_view_gap=None,
):
    if output.exists():
        raise ValueError("saved_graph_trial_output_exists")
    if not math.isfinite(from_seconds) or not 0 <= from_seconds <= 600:
        raise ValueError("saved_graph_invalid_start")
    if spatial_filter not in {None, "upper"}:
        raise ValueError("saved_graph_spatial_filter_invalid")
    if max_view_gap is not None and (
        type(max_view_gap) is not int or not 1 <= max_view_gap <= 16 or spatial_filter is not None
    ):
        raise ValueError("saved_graph_temporal_filter_invalid")
    prepared = source / "prepared"
    original = prepared / "database.db"
    wal = prepared / "database.db-wal"
    if not original.is_file() or wal.exists() and wal.stat().st_size:
        raise ValueError("saved_graph_source_database_unstable")
    geometry = json.loads((source / "geometry.json").read_bytes())
    provenance = json.loads((prepared / "reconstruction-input.json").read_bytes())
    if geometry.get("source_manifest_sha256") != provenance.get("source_manifest_sha256"):
        raise ValueError("saved_graph_source_binding")
    if evaluate(collect(ROOT), min_ram_gib=12):
        raise RuntimeError("saved_graph_resource_guard")
    selected = [
        row for row in provenance["images"] if row["relative_ticks_90k"] / 90000 >= from_seconds
    ]
    if not 10 <= len(selected) <= 240:
        raise ValueError("saved_graph_selected_view_quota")
    if any(
        b["relative_ticks_90k"] <= a["relative_ticks_90k"] for a, b in zip(selected, selected[1:])
    ):
        raise ValueError("saved_graph_selected_not_chronological")
    for row in selected:
        name = Path(row["image"]).name
        image = prepared / "images" / name
        if image.is_symlink() or not image.is_file() or digest(image) != row["png_sha256"]:
            raise ValueError("saved_graph_source_image_changed")
    sys.path.insert(0, str(TOOLS / "pycolmap-4.2.1"))
    import pycolmap as p

    if p.__version__ != "4.2.1":
        raise RuntimeError("saved_graph_pycolmap_version")
    intrinsics = geometry["cameras"][0]["intrinsics"]
    if intrinsics["fx"] != intrinsics["fy"] or not 0 < intrinsics["fx"] < 10000:
        raise ValueError("saved_graph_baseline_intrinsics")
    original_hash = digest(original)
    output.mkdir(parents=True)
    write_json(
        output / "intent.json",
        dict(
            scope="CPU_ESTIMATED_FOCAL_SFM",
            source_database_sha256=original_hash,
            baseline_geometry_sha256=digest(source / "geometry.json"),
            source_manifest_sha256=geometry["source_manifest_sha256"],
            focal_px=intrinsics["fx"],
            selected_from_seconds=from_seconds,
            selected_count=len(selected),
            focal_ground_truth=False,
            optimize_focal=optimize_focal,
            spatial_filter=spatial_filter,
            max_view_gap=max_view_gap,
            physical_actions=0,
            original_writes=False,
        ),
    )
    token, done, aborted = p.CancellationToken(), threading.Event(), []
    started = time.monotonic()

    def checkpoint():
        if (output / "CANCEL").exists():
            raise RuntimeError("cancelled")
        if evaluate(collect(ROOT), min_ram_gib=12):
            raise RuntimeError("saved_graph_resource_guard")
        if time.monotonic() - started > 600:
            raise RuntimeError("saved_graph_trial_timeout")

    def watchdog():
        while not done.wait(4):
            try:
                checkpoint()
            except Exception as exc:
                aborted.append(type(exc).__name__ + ":" + str(exc))
                token.cancel()
                return

    try:
        copied = output / "database.db"
        shutil.copyfile(original, copied)
        if digest(copied) != original_hash or digest(original) != original_hash:
            raise ValueError("saved_graph_database_changed_during_copy")
        with p.Database.open(copied) as db:
            cameras = db.read_all_cameras()
            if len(cameras) != 1 or cameras[0].model_name != "SIMPLE_PINHOLE":
                raise ValueError("saved_graph_camera_model_mismatch")
            camera = cameras[0]
            camera.params = [intrinsics["fx"], intrinsics["cx"], intrinsics["cy"]]
            # This is an algorithmic prior copied from an earlier estimate,
            # never evidence that the game camera is physically calibrated.
            if not optimize_focal:
                camera.has_prior_focal_length = True
            db.update_camera(camera)
        checkpoint()
        models = output / "models"
        models.mkdir()
        opts = p.IncrementalPipelineOptions(
            num_threads=4,
            random_seed=17,
            max_runtime_seconds=480,
            max_num_models=4,
            structure_less_registration_fallback=False,
            ba_refine_sensor_from_rig=False,
            ba_refine_focal_length=optimize_focal,
            ba_refine_principal_point=False,
            ba_refine_extra_params=False,
        )
        opts.mapper.abs_pose_refine_focal_length = optimize_focal
        opts.mapper.abs_pose_refine_extra_params = False
        if not optimize_focal:
            opts.constant_cameras = {camera.camera_id}
            opts.mapper.constant_cameras = {camera.camera_id}
        opts.image_names = {Path(row["image"]).name for row in selected}
        thread = threading.Thread(target=watchdog, daemon=True)
        thread.start()
        try:
            filter_receipt = None
            if max_view_gap is not None:
                from scripts.pilot.filter_sfm_temporal_graph import restrict_copied_database

                write_json(output / "state.json", dict(phase="filtering_temporal_pairs"))
                filter_receipt = restrict_copied_database(
                    copied,
                    [Path(row["image"]).name for row in selected],
                    max_view_gap,
                    checkpoint=checkpoint,
                )
                checkpoint()
            if spatial_filter == "upper":
                from scripts.pilot.filter_sfm_pair_graph import filter_copied_database

                write_json(output / "state.json", dict(phase="filtering_pairs"))
                pairs = output / "spatial-pairs.txt"
                filter_receipt = filter_copied_database(
                    copied,
                    [Path(row["image"]).name for row in selected],
                    pairs,
                    checkpoint=checkpoint,
                )
                checkpoint()
                write_json(output / "state.json", dict(phase="verifying_pairs"))
                verify_opts = p.TwoViewGeometryOptions()
                verify_opts.ransac.num_threads = 1
                p.verify_matches(copied, pairs, options=verify_opts, cancellation_token=token)
                if aborted:
                    raise RuntimeError(aborted[0])
                checkpoint()
            write_json(output / "state.json", dict(phase="mapping"))
            result = p.incremental_mapping(
                copied, prepared / "images", models, options=opts, cancellation_token=token
            )
        finally:
            done.set()
            thread.join(10)
        if aborted:
            raise RuntimeError(aborted[0])
        checkpoint()
        if not result:
            raise RuntimeError("saved_graph_no_reconstruction")
        selected_component, model = max(result.items(), key=lambda item: item[1].num_reg_images())
        if not optimize_focal:
            verify_fixed_focal(tuple(model.cameras.values()), intrinsics["fx"])
        recovered = model_geometry(model, prepared)
        write_json(output / "geometry.json", recovered)
        motion = audit(recovered)
        report = dict(
            scope="CPU_ESTIMATED_FOCAL_SFM_NOT_NAVIGATION",
            source_database_sha256=original_hash,
            source_database_unchanged=digest(original) == original_hash,
            source_manifest_sha256=geometry["source_manifest_sha256"],
            selected=len(selected),
            selected_from_seconds=from_seconds,
            registered=model.num_reg_images(),
            points=model.num_points3D(),
            components=len(result),
            selected_component=int(selected_component),
            reprojection_px=model.compute_mean_reprojection_error(),
            temporal=motion,
            initial_focal_px=intrinsics["fx"],
            optimize_focal=optimize_focal,
            resulting_focal_px=recovered["cameras"][0]["intrinsics"]["fx"],
            fixed_focal_verified=None if optimize_focal else True,
            physical_calibration_verified=False,
            same_saved_pair_graph=spatial_filter is None and max_view_gap is None,
            spatial_filter=spatial_filter,
            max_view_gap=max_view_gap,
            filter_receipt=filter_receipt,
            source_images_verified_before=True,
            physical_actions=0,
            execution_qualified=False,
            independent_replay=False,
            seconds=time.monotonic() - started,
        )
        write_json(output / "report.json", report)
        write_json(output / "state.json", dict(phase="complete"))
        print(json.dumps({k: v for k, v in report.items() if k != "temporal"}, indent=2))
    except Exception as exc:
        write_json(
            output / "state.json",
            dict(phase="failed", error=type(exc).__name__, message=str(exc)[:200]),
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--from-seconds", type=float, default=0.0)
    parser.add_argument("--optimize-focal", action="store_true")
    parser.add_argument("--spatial-filter", choices=("upper",))
    parser.add_argument("--max-view-gap", type=int)
    args = parser.parse_args()
    run(
        args.source,
        args.output,
        from_seconds=args.from_seconds,
        optimize_focal=args.optimize_focal,
        spatial_filter=args.spatial_filter,
        max_view_gap=args.max_view_gap,
    )
