"""Measured synthetic native rows: no solver, network, GPU or source mutation."""

from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import route_native_landmarks as native
from scripts.pilot.camera_pixel_conventions import colmap_calibration_to_opencv


def fixture(points=2):
    original = np.array([[800.0, 0, 640.0], [0, 800.0, 360.0], [0, 0, 1.0]])
    camera = SimpleNamespace(
        model_name="PINHOLE", width=1280, height=720, calibration_matrix=lambda: original
    )
    xyz = [np.array([i * 0.1, 0.2, 5.0], np.float64) for i in range(points)]
    ordered, features, rows, remaps = [], {}, [], {}
    point_map = {
        101 + i: SimpleNamespace(xyz=p, track=SimpleNamespace(elements=[]))
        for i, p in enumerate(xyz)
    }
    for view, center in enumerate((-1.0, 0.0, 1.0)):
        identity = view + 1
        matrix = np.c_[np.eye(3), [-center, 0, 0]]
        projected = np.asarray([(original @ (p - np.array([center, 0, 0]))) for p in xyz])
        pixels = (projected[:, :2] / projected[:, 2:]).astype(np.float32)
        keypoints = np.c_[pixels, np.ones((points, 2), np.float32)].astype(np.float32)
        desc = np.zeros((points, 128), np.uint8)
        for i in range(points):
            desc[i, i : i + 16] = 128
        point2d = [SimpleNamespace(xy=np.array([10.5, 10.5]), has_point3D=lambda: False)]
        for i, pixel in enumerate(pixels):
            point2d.append(
                SimpleNamespace(
                    xy=pixel.astype(np.float64), has_point3D=lambda: True, point3D_id=101 + i
                )
            )
            point_map[101 + i].track.elements.append(
                SimpleNamespace(image_id=identity, point2D_idx=i + 1)
            )
        image = SimpleNamespace(
            name=f"{view:08d}.png",
            image_id=identity,
            camera_id=1,
            points2D=point2d,
            cam_from_world=lambda matrix=matrix: SimpleNamespace(matrix=lambda: matrix),
        )
        ordered.append(image)
        features[identity] = (keypoints, desc)
        remaps[f"sift_{identity}"] = np.arange(1, points + 1, dtype=np.uint32)
        rows.append(
            dict(
                name=image.name,
                videoImageId=identity,
                siftImageId=identity,
                videoRows=1,
                siftRows=points,
                fusedRows=points + 1,
            )
        )
    rec = SimpleNamespace(cameras={1: camera}, points3D=point_map)
    K = colmap_calibration_to_opencv(original, (1280, 720), (960, 540))
    return rec, ordered, features, rows, remaps, K


def run(data, **kwargs):
    return native.build(
        *data,
        mask=kwargs.pop("mask", np.full((540, 960), 255, np.uint8)),
        checkpoint=kwargs.pop("checkpoint", lambda: None),
        **kwargs,
    )


def test_exact_native_ids_xyz_and_measured_descriptor_preserved_without_mutation():
    data = fixture()
    rec, images, features, _, _, _ = data
    xyz = {i: p.xyz.copy() for i, p in rec.points3D.items()}
    proof = []
    candidates, report, ids = run(data, provenance=proof)
    assert ids == [101, 102] and len(candidates) == 2
    assert report["triangulation_performed"] is False
    assert report["feature_association"] == "exact_row_mapping_only"
    for index, (row, identity) in enumerate(zip(candidates, ids)):
        np.testing.assert_array_equal(row[1], xyz[identity])
        np.testing.assert_array_equal(rec.points3D[identity].xyz, xyz[identity])
        expected = features[1][1][index].astype(np.float32)
        expected /= np.linalg.norm(expected)
        np.testing.assert_array_equal(row[2], expected)
        assert row[3] == (0, 1, 2)
        assert proof[index]["point3D_id"] == str(identity)
        assert proof[index]["descriptor_observation"] in proof[index]["observations"]
    assert len(images[0].points2D) == 3


def test_colmap_resize_half_pixel_is_applied_once_and_matches_native_projection():
    data = fixture()
    candidates, report, _ = run(data)
    assert len(candidates) == 2
    assert report["pixel_coordinates"] == "colmap_xy_times_scale_minus_half_v1"
    # Correct xy*scale-.5 differs from (xy-.5)*scale at every source center.
    native_xy = data[2][1][0][0, :2].astype(float)
    assert not np.array_equal(native_xy * 0.75 - 0.5, (native_xy - 0.5) * 0.75)
    changed = list(data)
    changed[-1] = data[-1].copy()
    changed[-1][0, 2] += 0.25
    with pytest.raises(ValueError, match="calibration_binding"):
        run(changed)


def test_wrong_map_or_native_reciprocity_fails_closed_instead_of_nearest_pixel_rescue():
    data = fixture()
    data[4]["sift_1"][0] = 2
    with pytest.raises(ValueError, match="exact_xy_binding"):
        run(data)
    data = fixture()
    data[1][0].points2D[1].point3D_id = 999
    with pytest.raises(ValueError, match="reciprocity"):
        run(data)


def test_masked_or_bad_native_point_is_rejected_not_retriangulated():
    data = fixture()
    data[0].points3D[101].xyz[0] += 1
    candidates, report, ids = run(data)
    assert ids == [102] and len(candidates) == 1
    assert report["rejected"]["reprojection_over_3px"] == 1
    mask = np.zeros((540, 960), np.uint8)
    candidates, report, ids = run(fixture(), mask=mask)
    assert not candidates and not ids
    assert report["rejected"]["outside_capture_world_mask"] == 2


def test_minimum_three_views_and_track_uniqueness_stay_required():
    data = fixture()
    data[0].points3D[101].track.elements.pop()
    _, report, ids = run(data)
    assert ids == [102] and report["rejected"]["fewer_than_3_sift_views"] == 1
    data = fixture()
    data[0].points3D[101].track.elements.append(data[0].points3D[101].track.elements[0])
    with pytest.raises(ValueError, match="duplicate_observation"):
        run(data)


def test_wrong_descriptor_dtype_and_cache_quota_do_not_return_partial_proof(monkeypatch):
    data = fixture()
    data[2][1] = (data[2][1][0], data[2][1][1].astype(np.float32))
    with pytest.raises(ValueError, match="feature_rows"):
        run(data)
    monkeypatch.setattr(native, "MAX_FEATURE_BYTES", 1)
    proof = []
    with pytest.raises(ValueError, match="feature_quota"):
        run(fixture(), provenance=proof)
    assert proof == []


def test_cancellation_propagates_without_publication_or_source_changes():
    data = fixture()
    before = data[0].points3D[101].xyz.copy()
    proof = []

    def cancel():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        run(data, checkpoint=cancel, provenance=proof)
    assert proof == []
    np.testing.assert_array_equal(before, data[0].points3D[101].xyz)


def test_balanced_selection_preserves_native_ids_and_observed_view_deficits():
    candidates = []
    ids = []
    for index in range(100):
        views = (0, 1, 2) if index < 60 else (2, 3, 4)
        candidates.append(
            (3, (index * 0.01, 0.0, 5.0), np.ones(128, np.float32) / np.sqrt(128), views)
        )
        ids.append(1000 + index)
    matrices = [np.c_[np.eye(3), [0, 0, 0]] for _ in range(5)]
    chosen, report = native.select_balanced(
        candidates,
        ids,
        matrices,
        np.array([[500, 0, 480], [0, 500, 270], [0, 0, 1]]),
        limit=60,
        checkpoint=lambda: None,
    )
    assert len(chosen) == 60 and len(set(chosen)) == 60
    assert report["minimum_view_support"] >= 24 and report["views_below_24"] == 0
    assert all(ids[index] >= 1000 for index in chosen)
    assert (
        chosen
        == native.select_balanced(
            candidates,
            ids,
            matrices,
            np.array([[500, 0, 480], [0, 500, 270], [0, 0, 1]]),
            limit=60,
            checkpoint=lambda: None,
        )[0]
    )


def test_readonly_sqlite_cache_preserves_bytes_and_rejects_bad_rows_before_loading(tmp_path):
    import hashlib
    import sqlite3

    data = fixture()
    features, rows, remaps = data[2:5]
    db = tmp_path / "sift.db"
    mapping = tmp_path / "mapping.npz"
    with sqlite3.connect(db) as connection:
        connection.executescript(
            "CREATE TABLE images(image_id INTEGER,name TEXT);CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);CREATE TABLE descriptors(image_id INTEGER,type INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
        )
        for row in rows:
            i = row["siftImageId"]
            xy, desc = features[i]
            connection.execute("INSERT INTO images VALUES(?,?)", (i, row["name"]))
            connection.execute("INSERT INTO keypoints VALUES(?,?,4,?)", (i, len(xy), xy.tobytes()))
            connection.execute(
                "INSERT INTO descriptors VALUES(?,0,?,128,?)", (i, len(desc), desc.tobytes())
            )
    np.savez_compressed(mapping, **remaps)
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    loaded, maps = native.read_feature_cache(db, mapping, rows, checkpoint=lambda: None)
    assert before == hashlib.sha256(db.read_bytes()).hexdigest()
    np.testing.assert_array_equal(loaded[1][0], features[1][0])
    np.testing.assert_array_equal(maps["sift_1"], remaps["sift_1"])
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE descriptors SET rows=99999999")
    with pytest.raises(ValueError, match="database_namespace"):
        native.read_feature_cache(db, mapping, rows, checkpoint=lambda: None)


def reference_receipt(folder, source_sha="1" * 64, index_sha="2" * 64):
    import gzip
    import hashlib
    import json
    import uuid

    from motor_worker.landmarks import RouteViewProfile
    from motor_worker.route_localization import (
        SparseRoute,
        native_reference_pipeline_id,
        pipeline_id,
    )

    route = SparseRoute(
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        "a" * 64,
        native_reference_pipeline_id(),
        RouteViewProfile(
            str(uuid.uuid4()), 960, 540, (0.0, 0.0, 1.0, 1.0), ((0.99, 0.99, 1.0, 1.0),)
        ),
        (500.0, 500.0, 480.0, 270.0),
        tuple((float(i), 0.0, 5.0) for i in range(24)),
        np.full((24, 128), 1 / np.sqrt(128), dtype="<f4").tobytes(),
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
        (0.0, 0.2, 0.4),
        ("a" * 64,) * 3,
        ((0, 1, 2),) * 24,
        source_sha,
        (0, 1, 2),
    )
    (folder / "route.json").unlink(missing_ok=True)
    route_sha = route.save(folder / "route.json")

    binding = dict(
        model={name: "a" * 64 for name in ("cameras.bin", "images.bin", "points3D.bin")},
        namespace="b" * 64,
        row_mapping="c" * 64,
        sift_database="d" * 64,
        mask="e" * 64,
    )
    block = dict(
        schema="sphere-native-reference-contract-v1",
        runtime_qualified=False,
        descriptor_family=native.FAMILY,
        export_version=native.EXPORT_VERSION,
        query_pipeline_sha256=pipeline_id(),
        pipeline_sha256=native_reference_pipeline_id(),
        source_manifest_sha256=source_sha,
        source_index_sha256=index_sha,
        cache_binding=binding,
        cache_binding_sha256=native._digest(binding),
    )
    rows = [
        dict(
            view=v,
            native_image_id=v + 1,
            fused_row=10,
            sift_image_id=v + 1,
            sift_row=0,
            reprojection_px=0.2,
        )
        for v in range(3)
    ]
    proof = dict(
        schema="sphere-native-landmark-provenance-v1",
        runtime_qualified=False,
        route_sha256=route_sha,
        cache_binding_sha256=block["cache_binding_sha256"],
        pipeline_sha256=block["pipeline_sha256"],
        source_manifest_sha256=block["source_manifest_sha256"],
        source_index_sha256=index_sha,
        landmarks=[],
    )
    for i in range(24):
        observations = [dict(row, fused_row=10 + i, sift_row=i) for row in rows]
        proof["landmarks"].append(
            dict(
                point3D_id=str(i), observations=observations, descriptor_observation=observations[0]
            )
        )
    raw = gzip.compress(json.dumps(proof).encode(), mtime=0)
    (folder / "native-landmarks.json.gz").write_bytes(raw)
    block["provenance"] = dict(
        file="native-landmarks.json.gz", sha256=hashlib.sha256(raw).hexdigest()
    )
    return dict(
        sha256=route_sha,
        pipeline_sha256=block["pipeline_sha256"],
        cameras=3,
        landmarks=24,
        native_reference=block,
    ), proof


def validate(receipt, folder):
    native.validate_reference_receipt(
        receipt, folder, source_sha256="1" * 64, source_index_sha256="2" * 64
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("query_pipeline_sha256", "0" * 64),
        ("descriptor_family", "native_colmap_rootsift_q512_l2_v1_lookalike"),
        ("source_manifest_sha256", "0" * 64),
        ("source_index_sha256", "0" * 64),
        ("export_version", "unverified"),
        ("runtime_qualified", True),
    ],
)
def test_native_reference_rejects_stale_query_family_or_source_even_after_cached_validation(
    tmp_path, field, value
):
    receipt, _ = reference_receipt(tmp_path)
    validate(receipt, tmp_path)
    receipt["native_reference"][field] = value
    with pytest.raises(ValueError, match="native_reference_invalid"):
        validate(receipt, tmp_path)


def test_native_reference_rejects_modified_receipt_binding_and_proof_bytes(tmp_path):
    receipt, _ = reference_receipt(tmp_path)
    validate(receipt, tmp_path)
    receipt["native_reference"]["cache_binding"]["sift_database"] = "0" * 64
    with pytest.raises(ValueError, match="native_reference_invalid"):
        validate(receipt, tmp_path)
    receipt, _ = reference_receipt(tmp_path)
    validate(receipt, tmp_path)
    (tmp_path / "native-landmarks.json.gz").write_bytes(b"edited")
    with pytest.raises(ValueError, match="native_reference_invalid"):
        validate(receipt, tmp_path)


@pytest.mark.parametrize("badrow", [None, {}, dict(point3D_id="1", observations=[])])
def test_native_reference_malformed_provenance_fails_closed(tmp_path, badrow):
    import gzip
    import hashlib
    import json

    receipt, proof = reference_receipt(tmp_path)
    proof["landmarks"][0] = badrow
    raw = gzip.compress(json.dumps(proof).encode(), mtime=0)
    (tmp_path / "native-landmarks.json.gz").write_bytes(raw)
    receipt["native_reference"]["provenance"]["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="native_reference_invalid"):
        validate(receipt, tmp_path)


def test_runtime_accepts_only_exact_native_family_and_unchanged_query_fingerprint(monkeypatch):
    from dataclasses import replace

    from motor_worker import route_localization as runtime
    from motor_worker.protocol import ProtocolError
    from tests.test_motor_route_localization import SparseLocalizationTests

    fixture = SparseLocalizationTests("test_blank_real_rgb_has_no_pose")
    fixture.setUp()
    native_id = runtime.native_reference_pipeline_id()
    route = replace(fixture.route, pipeline_sha256=native_id)
    assert fixture.tracker(route).route is route
    with pytest.raises(ProtocolError, match="binding"):
        fixture.tracker(replace(route, pipeline_sha256="0" * 64))
    monkeypatch.setattr(runtime, "pipeline_id", lambda: "f" * 64)
    with pytest.raises(ProtocolError, match="binding"):
        fixture.tracker(route)


def bundle_fixture(tmp_path):
    import hashlib
    import json
    import sqlite3
    from pathlib import Path

    import cv2 as cv

    job = tmp_path / "job"
    folder = job / "prepared/fused-recovery"
    model = job / "prepared/sparse/0"
    folder.mkdir(parents=True)
    model.mkdir(parents=True)
    (job / "input").mkdir()
    (job / "prepared/images").mkdir()
    (folder / "model").mkdir()
    (folder / "detector-masks").mkdir()
    data = fixture(points=24)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write(path, value):
        path.write_text(json.dumps(value), encoding="utf8")

    (job / "input/manifest.json").write_text("{}")
    source = []
    mask_records = []
    for index, row in enumerate(data[3]):
        name = row["name"]
        image = job / "prepared/images" / name
        assert cv.imwrite(str(image), np.zeros((720, 1280, 3), np.uint8))
        row["sourcePngSHA"] = digest(image)
        source.append(
            dict(
                image="images/" + name,
                png_sha256=digest(image),
                source_index=index * 10,
                relative_ticks_90k=index * 18000,
            )
        )
        mask = np.full((720, 1280), 255, np.uint8)
        mask[int(720 * 0.975) :] = 0
        path = folder / "detector-masks" / name
        assert cv.imwrite(str(path), mask)
        mask_records.append(
            dict(
                image=name,
                supplied_mask_sha256=None,
                effective_mask=dict(path="detector-masks/" + name, sha256=digest(path)),
                width=1280,
                height=720,
            )
        )
    write(
        job / "prepared/reconstruction-input.json",
        dict(source_manifest_sha256=digest(job / "input/manifest.json"), images=source),
    )
    for name in ("cameras.bin", "images.bin", "points3D.bin"):
        (folder / "model" / name).write_bytes(name.encode())
        (model / name).write_bytes(name.encode())
    with sqlite3.connect(folder / "sift.db") as db:
        db.executescript(
            "CREATE TABLE images(image_id INTEGER,name TEXT);CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);CREATE TABLE descriptors(image_id INTEGER,type INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
        )
        for row in data[3]:
            i = row["siftImageId"]
            xy, desc = data[2][i]
            db.execute("INSERT INTO images VALUES(?,?)", (i, row["name"]))
            db.execute("INSERT INTO keypoints VALUES(?,?,4,?)", (i, len(xy), xy.tobytes()))
            db.execute(
                "INSERT INTO descriptors VALUES(?,0,?,128,?)", (i, len(desc), desc.tobytes())
            )
    (folder / "database.db").write_bytes(b"not loaded as native descriptor database")
    np.savez_compressed(folder / "row-remapping.npz", **data[4])
    namespace = dict(
        schema="sphere-fused-route-namespace-v1",
        sift_descriptors="quantized_rootsift_round512_uint8",
        source_sift_database_sha256=digest(folder / "sift.db"),
        row_remapping_sha256=digest(folder / "row-remapping.npz"),
        images=data[3],
    )
    write(folder / "namespace.json", namespace)
    write(
        folder / "detector-masks.json",
        dict(
            schema="sphere-fused-detector-masks-v1",
            source_manifest_sha256=digest(job / "input/manifest.json"),
            reconstruction_input_sha256=digest(job / "prepared/reconstruction-input.json"),
            declared_profile=dict(mode=None, hudProfile=None, hud_hidden_declared=None),
            supplied_mask_producer="unknown_hash_bound_pixels",
            detector_footer_exclusion_y=0.975,
            producer_sources={
                "scripts/pilot/learned_route_features.py": digest(
                    Path(native.__file__).with_name("learned_route_features.py")
                )
            },
            images=mask_records,
        ),
    )
    paths = dict(
        namespace="namespace.json",
        row_mapping="row-remapping.npz",
        sift_database="sift.db",
        fused_database="database.db",
        mask_provenance="detector-masks.json",
    )
    result = dict(
        schema="sphere-fused-route-recovery-v1",
        accepted=True,
        execution_qualified=False,
        source_modified=False,
        source_manifest_sha256=digest(job / "input/manifest.json"),
        reconstruction_input_sha256=digest(job / "prepared/reconstruction-input.json"),
        model_sha256={p.name: digest(p) for p in (folder / "model").glob("*.bin")},
        assets={k: dict(path=v, sha256=digest(folder / v)) for k, v in paths.items()},
        native_landmark_bundle=dict(
            model="model",
            namespace="namespace.json",
            row_mapping="row-remapping.npz",
            sift_database="sift.db",
            float_features="sift-features",
            mask_provenance="detector-masks.json",
        ),
    )
    write(folder / "result.json", result)
    return job, model, data, result


def test_bundle_source_model_masks_and_cache_are_hash_bound_without_source_mutation(tmp_path):
    import hashlib

    job, model, _, _ = bundle_fixture(tmp_path)
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in job.rglob("*") if p.is_file()
    }
    bundle, reason = native.selected_bundle(job, model, checkpoint=lambda: None)
    assert reason == "exact_native_bundle_selected" and len(bundle["namespace"]) == 3
    native.verify_bundle_unchanged(bundle, checkpoint=lambda: None)
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in job.rglob("*") if p.is_file()
    }
    (job / "prepared/images/00000000.png").write_bytes(b"wrong source")
    with pytest.raises(ValueError, match="source_changed"):
        native.selected_bundle(job, model, checkpoint=lambda: None)


def test_bundle_different_selected_model_has_explicit_legacy_fallback_without_relabeling(tmp_path):
    job, model, _, _ = bundle_fixture(tmp_path)
    (model / "points3D.bin").write_bytes(b"endpoint repair changed native points")
    bundle, reason = native.selected_bundle(job, model, checkpoint=lambda: None)
    assert bundle is None and reason == "native_engine_model_not_selected_or_modified"


@pytest.mark.parametrize("asset", ["namespace", "row_mapping", "sift_database", "mask_provenance"])
def test_changed_accepted_native_cache_never_silently_falls_back(tmp_path, asset):
    job, model, _, result = bundle_fixture(tmp_path)
    (job / "prepared/fused-recovery" / result["assets"][asset]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="source_changed"):
        native.selected_bundle(job, model, checkpoint=lambda: None)


def test_raw_sift_cannot_claim_q512_compatibility_even_with_updated_asset_hash(
    tmp_path,
):
    import hashlib
    import json

    job, model, _, result = bundle_fixture(tmp_path)
    folder = job / "prepared/fused-recovery"
    namespace = json.loads((folder / "namespace.json").read_bytes())
    namespace["sift_descriptors"] = "raw_sift_uint8"
    (folder / "namespace.json").write_text(json.dumps(namespace))
    result["assets"]["namespace"]["sha256"] = hashlib.sha256(
        (folder / "namespace.json").read_bytes()
    ).hexdigest()
    (folder / "result.json").write_text(json.dumps(result))
    with pytest.raises(ValueError, match="descriptor_family"):
        native.selected_bundle(job, model, checkpoint=lambda: None)


def test_export_status_rejects_edited_actual_route_after_cached_proof_validation(tmp_path):
    receipt, _ = reference_receipt(tmp_path)
    validate(receipt, tmp_path)
    (tmp_path / "route.json").write_bytes(b"changed descriptor rows")
    with pytest.raises(ValueError, match="native_reference_invalid"):
        validate(receipt, tmp_path)


def test_native_export_runs_no_detector_matching_or_triangulation_and_is_offline_only(
    tmp_path, monkeypatch
):
    import hashlib
    import sys
    import uuid

    from motor_worker import route_localization as runtime
    from motor_worker.landmarks import RouteViewProfile

    job, model, data, _ = bundle_fixture(tmp_path)
    rec, ordered = data[:2]
    rec.images = {im.image_id: im for im in ordered}
    rec.num_cameras = lambda: 1
    rec.num_reg_images = lambda: 3
    for im in ordered:
        matrix = im.cam_from_world().matrix()
        im.cam_from_world = lambda matrix=matrix: SimpleNamespace(
            matrix=lambda: matrix,
            inverse=lambda: SimpleNamespace(translation=-matrix[:, :3].T @ matrix[:, 3]),
        )
    monkeypatch.setitem(sys.modules, "pycolmap", SimpleNamespace(Reconstruction=lambda path: rec))

    def forbidden(*args, **kwargs):
        raise AssertionError("native export must never extract or triangulate")

    monkeypatch.setattr(runtime, "extract_features", forbidden)
    from scripts.pilot import route_landmark_builder

    monkeypatch.setattr(route_landmark_builder, "build", forbidden)
    before = {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in job.rglob("*") if p.is_file()
    }
    bundle, _ = native.selected_bundle(job, model, checkpoint=lambda: None)
    output = tmp_path / "output"
    output.mkdir()
    profile = RouteViewProfile(
        str(uuid.uuid4()), 1280, 720, (0.0, 0.0, 1.0, 1.0), ((0.99, 0.99, 1.0, 1.0),)
    )
    receipt = native.export(
        bundle,
        job / "prepared/reconstruction-input.json",
        job / "prepared/images",
        output / "route.json",
        profile=profile,
        world_revision=str(uuid.uuid4()),
        checkpoint_fn=lambda path: None,
    )
    loaded = runtime.SparseRoute.load(output / "route.json", sha256=receipt["sha256"])
    assert (
        len(loaded.points) == 24
        and loaded.pipeline_sha256 == runtime.native_reference_pipeline_id()
    )
    assert receipt["native_reference"]["runtime_qualified"] is False
    assert receipt["feature_build"]["triangulation_performed"] is False
    assert receipt["map_support"]["all_reference_neighborhoods_supported"] is True
    assert before == {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in job.rglob("*") if p.is_file()
    }


def test_structurally_supported_native_map_cannot_be_ready_or_start_live(tmp_path):
    import hashlib
    import json

    from scripts.pilot.route_workspace import RouteWorkspaces

    job = tmp_path / "job"
    folder = job / "navigation" / ("a" * 32)
    folder.mkdir(parents=True)
    (job / "input").mkdir()
    (job / "prepared").mkdir()
    for name in ("input/manifest.json", "prepared/reconstruction-input.json", "geometry.json"):
        (job / name).write_text("{}")
    source = hashlib.sha256(b"{}").hexdigest()
    receipt, _ = reference_receipt(folder, source, source)
    receipt.update(
        geometry_sha256=source,
        source_capture_sha256=source,
        map_support=dict(
            all_reference_neighborhoods_supported=True, all_reference_intervals_observed=True
        ),
        source_coverage=dict(endpoints_observed=True),
    )
    (folder / "state.json").write_text('{"phase":"ready"}')
    (folder / "receipt.json").write_text(json.dumps(receipt))
    (folder.parent / "active.json").write_text(json.dumps(dict(id=folder.name)))
    workspace = RouteWorkspaces(tmp_path, "not invoked")
    assert workspace.status(job)["error"] == "route_native_reference_unqualified"
    with pytest.raises(ValueError, match="assets_not_ready"):
        workspace.start_live(
            job,
            dict(id="b" * 32, captureEpoch="c" * 32, width=960, height=540, sceneConfirmed=True),
        )
