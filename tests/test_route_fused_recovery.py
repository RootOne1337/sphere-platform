import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.pilot import route_fused_recovery as fused


def database(path, *, sift=False, bad_match=False):
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE cameras(camera_id INTEGER,model INTEGER,width INTEGER,height INTEGER,params BLOB);"
            "CREATE TABLE images(image_id INTEGER,name TEXT,camera_id INTEGER);"
            "CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
            "CREATE TABLE descriptors(image_id INTEGER,type INTEGER NOT NULL,rows INTEGER,cols INTEGER,data BLOB);"
            "CREATE TABLE matches(pair_id INTEGER PRIMARY KEY,rows INTEGER,cols INTEGER,data BLOB);"
            "CREATE TABLE two_view_geometries(pair_id INTEGER PRIMARY KEY,rows INTEGER,cols INTEGER,data BLOB);"
        )
        db.execute(
            "INSERT INTO cameras VALUES(1,0,200,100,?)", (np.array([100.0, 100.0, 50.0]).tobytes(),)
        )
        ids = [3, 1] if sift else [10, 20]
        for n, identity in enumerate(ids):
            db.execute("INSERT INTO images VALUES(?,?,1)", (identity, f"{n:08}.png"))
            xy = np.array(
                [[0.5, 0.5, 1.0, 0.0], [0.5, 0.5, 1.0, 1.0], [20.5, 10.5, 2.0, 0.0]]
                if sift
                else [[0.5, 0.5, 1.0, 0.0], [10.5, 10.5, 1.0, 0.0]],
                dtype="<f4",
            )
            db.execute("INSERT INTO keypoints VALUES(?,?,4,?)", (identity, len(xy), xy.tobytes()))
            db.execute(
                "INSERT INTO descriptors VALUES(?,0,?,128,?)",
                (identity, len(xy), bytes(len(xy) * 128)),
            )
        a, b = (1, 3) if sift else (10, 20)
        match = np.array([[0, 2]] if sift else [[99 if bad_match else 0, 1]], dtype="<u4")
        db.execute("INSERT INTO matches VALUES(?,1,2,?)", (fused._pair_id(a, b), match.tobytes()))


def test_explicit_row_remap_preserves_video_prefix_and_exact_sift_aliases_without_cross_family_aliasing(
    tmp_path,
):
    video, sift, out = tmp_path / "video.db", tmp_path / "sift.db", tmp_path / "out"
    database(video)
    database(sift, sift=True)
    out.mkdir()
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (video, sift)}
    report = fused.fuse_databases(
        video, sift, out, image_bindings={"00000000.png": "a" * 64, "00000001.png": "b" * 64}
    )
    mapping = np.load(out / "row-remapping.npz")
    assert mapping["sift_3"].tolist() == [2, 2, 3]
    assert all(row["fusedRows"] == 4 and row["exactSiftAliases"] == 1 for row in report["images"])
    assert report["video_prefix_preserved"] and report["video_and_sift_distinct"]
    assert report["images"][0]["sourcePngSHA"] in {"a" * 64, "b" * 64}
    with sqlite3.connect(out / "database.db") as db:
        assert db.execute("SELECT COUNT(*) FROM descriptors").fetchone()[0] == 0
        nr, blob = db.execute("SELECT rows,data FROM matches").fetchone()
        assert nr == 2
        assert np.frombuffer(blob, "<u4").reshape(-1, 2).tolist() == [[0, 1], [3, 2]]
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before} == before


def test_fusion_refuses_camera_mismatch_and_out_of_namespace_video_matches(tmp_path):
    video, sift = tmp_path / "video.db", tmp_path / "sift.db"
    database(video, bad_match=True)
    database(sift, sift=True)
    out = tmp_path / "bad-index"
    out.mkdir()
    with pytest.raises(ValueError, match="fused_match_index"):
        fused.fuse_databases(video, sift, out)
    with sqlite3.connect(sift) as db:
        db.execute("UPDATE cameras SET width=201")
    other = tmp_path / "bad-camera"
    other.mkdir()
    with pytest.raises(ValueError, match="fused_camera_namespace"):
        fused.fuse_databases(video, sift, other)


def test_every_owned_sqlite_handle_is_closed_before_native_handoff(tmp_path, monkeypatch):
    video, sift, out = tmp_path / "video.db", tmp_path / "sift.db", tmp_path / "out"
    database(video)
    database(sift, sift=True)
    out.mkdir()
    opened = []
    connect = sqlite3.connect

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            self.closed = True
            super().close()

    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs, factory=TrackedConnection)
        connection.closed = False
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked)
    fused.fuse_databases(video, sift, out)
    fused._native_database_boundary(out, "before_native_fixture", lambda: None)
    assert opened and all(connection.closed for connection in opened)
    record = json.loads((out / "database-boundaries.json").read_bytes())["boundaries"][0]
    assert record["owned_sqlite_handles_explicitly_closed"] and record["wal_bytes"] == 0
    assert record["main_sha256"] == hashlib.sha256((out / "database.db").read_bytes()).hexdigest()


def test_existing_candidate_database_is_never_overwritten(tmp_path):
    source, target = tmp_path / "source", tmp_path / "target"
    target.write_bytes(b"previous evidence")
    with pytest.raises(FileExistsError):
        fused._database_backup(source, target)
    assert target.read_bytes() == b"previous evidence"


def test_owned_wal_snapshot_is_closed_and_main_hash_survives_gc_and_reopen(tmp_path):
    import gc

    original, target = tmp_path / "original.db", tmp_path / "owned.db"
    with closing(sqlite3.connect(original)) as source:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE measured(value INTEGER)")
        source.execute("INSERT INTO measured VALUES(17)")
        source.commit()
        callbacks = []
        fused._database_backup(original, target, check=lambda: callbacks.append(True))
        assert callbacks
        expected = hashlib.sha256(target.read_bytes()).hexdigest()
        wal = Path(str(target) + "-wal")
        assert not wal.exists() or wal.stat().st_size == 0
        gc.collect()
        with closing(sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)) as snapshot:
            assert snapshot.execute("SELECT * FROM measured").fetchall() == [(17,)]
        gc.collect()
        assert hashlib.sha256(target.read_bytes()).hexdigest() == expected


def test_owned_database_cannot_be_sealed_over_pending_reader_wal_bytes(tmp_path):
    path = tmp_path / "owned.db"
    with closing(sqlite3.connect(path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE measured(value INTEGER)")
        writer.execute("INSERT INTO measured VALUES(17)")
        writer.commit()
        with closing(sqlite3.connect(path)) as reader:
            reader.execute("BEGIN")
            reader.execute("SELECT * FROM measured").fetchall()
            writer.execute("INSERT INTO measured VALUES(19)")
            writer.commit()
            with pytest.raises(ValueError, match="fused_database_not_sealed"):
                fused._seal_database(path)
        writer.commit()
    fused._seal_database(path)
    assert not Path(str(path) + "-wal").exists()


def test_appearance_retrieval_is_deterministic_bounded_and_blank_images_do_not_force_loop_closure():
    signatures = np.zeros((40, 576), dtype=np.float32)
    pairs = fused.propose_pairs(signatures)
    assert all(kind == "temporal" for _, _, kind in pairs)
    signatures[0, 0] = signatures[30, 0] = 1.0
    pairs = fused.propose_pairs(signatures)
    assert (0, 30, "appearance_loop_proposal") in pairs
    assert pairs == fused.propose_pairs(signatures)
    assert len(pairs) <= fused.MAX_PAIRS
    assert all(
        abs(a - b) >= fused.LOOP_MIN_SEPARATION for a, b, kind in pairs if kind != "temporal"
    )


def test_actual_geometric_verification_uses_train_matches_only_and_retains_withheld_rows():
    random = np.random.default_rng(17)
    xyz = random.uniform([-3.0, -2.0, 6.0], [3.0, 2.0, 14.0], (80, 3))

    def project(points):
        return np.column_stack(
            [
                500.0 * points[:, 0] / points[:, 2] + 640.5,
                500.0 * points[:, 1] / points[:, 2] + 360.5,
            ]
        ).astype("<f4")

    xy_a, xy_b = project(xyz), project(xyz + [-1.0, 0.0, 0.0])
    descriptors = random.uniform(0.0, 1.0, (80, 128)).astype(np.float32)
    descriptors /= np.linalg.norm(descriptors, axis=1, keepdims=True)
    accepted, heldout = fused.verified_matches(
        xy_a, descriptors, xy_b, descriptors.copy(), holdout=True
    )
    assert len(accepted) >= 50 and len(heldout) == 16
    assert not set(map(tuple, accepted)) & set(map(tuple, heldout))


def test_degenerate_usac_model_rejects_only_the_pair_without_weak_fallback(monkeypatch):
    import cv2 as cv

    xy = np.column_stack([np.arange(40), np.arange(40) * 2]).astype(np.float32)
    desc = np.zeros((40, 128), dtype=np.float32)
    monkeypatch.setattr(fused, "_ratio_matches", lambda *args: [(i, i) for i in range(40)])

    def fail_model(*args, **kwargs):
        raise cv.error("degenerate model")

    monkeypatch.setattr(cv, "findFundamentalMat", fail_model)
    counts = {}
    accepted, heldout = fused.verified_matches(
        xy, desc, xy.copy(), desc, holdout=True, diagnostics=counts
    )
    assert accepted.shape == (0, 2) and len(heldout) == 8
    assert counts == dict(fundamental_model_error=1)


@pytest.mark.parametrize("kind", ["rank3", "nonfinite", "nonbinary_mask", "bad_index"])
def test_fundamental_constraints_require_finite_rank2_matrix_and_valid_measured_rows(
    monkeypatch, kind
):
    import cv2 as cv

    xy = np.column_stack([np.arange(40), np.arange(40) * 2]).astype(np.float32)
    desc = np.zeros((40, 128), dtype=np.float32)
    monkeypatch.setattr(
        fused,
        "_ratio_matches",
        lambda *args: [(i, i) for i in range(40)] + ([(40, 0)] if kind == "bad_index" else []),
    )
    matrix = np.diag([1.0, 1.0, 0.0])
    mask = np.ones((40, 1), dtype=np.float64)
    if kind == "rank3":
        matrix = np.eye(3)
    elif kind == "nonfinite":
        matrix[0, 0] = np.nan
    elif kind == "nonbinary_mask":
        mask[0] = np.nan
    monkeypatch.setattr(cv, "findFundamentalMat", lambda *args, **kwargs: (matrix, mask))
    if kind == "bad_index":
        with pytest.raises(ValueError, match="fused_match_index"):
            fused.verified_matches(xy, desc, xy, desc)
    else:
        counts = {}
        accepted, _ = fused.verified_matches(xy, desc, xy, desc, diagnostics=counts)
        assert not len(accepted) and counts == dict(fundamental_model_invalid=1)


def source(tmp_path):
    job = tmp_path / "job"
    prepared = job / "prepared"
    (job / "input").mkdir(parents=True)
    (prepared / "images").mkdir(parents=True)
    manifest = json.dumps(dict(config=dict(profile=dict(mode="walking")))).encode()
    (job / "input/manifest.json").write_bytes(manifest)
    rows = []
    for i in range(14):
        name = f"images/{i:08}.png"
        (prepared / name).write_bytes(bytes([i]))
        rows.append(
            dict(
                image=name,
                png_sha256=hashlib.sha256(bytes([i])).hexdigest(),
                source_index=i,
                relative_ticks_90k=i * 45000,
            )
        )
    (prepared / "reconstruction-input.json").write_text(
        json.dumps(dict(source_manifest_sha256=hashlib.sha256(manifest).hexdigest(), images=rows))
    )
    (prepared / "database.db").write_bytes(b"original graph")
    return job, prepared


def test_inconclusive_or_unavailable_native_engine_keeps_baseline_and_one_immutable_attempt(
    tmp_path, monkeypatch
):
    job, prepared = source(tmp_path)
    baseline = object()
    monkeypatch.setitem(sys.modules, "pycolmap", SimpleNamespace(__version__="4.2.1"))
    monkeypatch.setattr(fused, "COLMAP", tmp_path / "missing.exe")

    def native(*args):
        pytest.fail("unavailable native tool must never be run")

    chosen, report = fused.recover_fused(
        job,
        prepared,
        baseline,
        14,
        0.0,
        6.5,
        lambda: None,
        lambda *args: None,
        native_runner=native,
    )
    assert (
        chosen is baseline
        and not report["accepted"]
        and report["reason"] == "fused_native_unavailable"
    )
    assert report["source_modified"] is False
    result = (prepared / "fused-recovery/result.json").read_bytes()
    chosen, second = fused.recover_fused(
        job, prepared, baseline, 14, 0.0, 6.5, lambda: None, lambda *args: None
    )
    assert chosen is baseline and second["reason"] == "fused_existing_intent"
    assert (prepared / "fused-recovery/result.json").read_bytes() == result


def test_source_pixel_hash_and_cancellation_are_checked_before_candidate_creation(tmp_path):
    job, prepared = source(tmp_path)
    (prepared / "images/00000000.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="fused_source_image_changed"):
        fused.recover_fused(job, prepared, object(), 14, 0.0, 6.5, lambda: None, lambda *args: None)
    assert not (prepared / "fused-recovery").exists()

    def cancelled():
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        fused.recover_fused(job, prepared, object(), 14, 0.0, 6.5, cancelled, lambda *args: None)


@pytest.mark.parametrize("field", ["source_index", "relative_ticks_90k"])
def test_source_order_must_remain_measured_and_strictly_increasing(tmp_path, field):
    job, prepared = source(tmp_path)
    index = prepared / "reconstruction-input.json"
    value = json.loads(index.read_bytes())
    value["images"][1][field] = value["images"][0][field]
    index.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="fused_source_order"):
        fused.recover_fused(job, prepared, object(), 14, 0.0, 6.5, lambda: None, lambda *args: None)
    assert not (prepared / "fused-recovery").exists()


@pytest.mark.parametrize("native_schema", [False, True])
def test_sift_detector_saves_exact_effective_mask_and_records_supplied_pixels(
    tmp_path, monkeypatch, native_schema
):
    import cv2 as cv

    from scripts.pilot import learned_route_features

    prepared, output = tmp_path / "prepared", tmp_path / "owned"
    (prepared / "images").mkdir(parents=True)
    (prepared / "masks").mkdir()
    output.mkdir()
    original = prepared / "database.db"
    if native_schema:
        if sys.version_info[:2] != (3, 12):
            pytest.skip("installed pinned native wheel uses cp312")
        p = pytest.importorskip("pycolmap")
        assert p.__version__ == "4.2.1" and int(p.FeatureExtractorType.SIFT) == 0
        with p.Database.open(original) as db:
            camera_id = db.write_camera(
                p.Camera(model="SIMPLE_PINHOLE", width=200, height=100, params=[100.0, 100.0, 50.0])
            )
            for index in range(2):
                db.write_image(p.Image(name=f"{index:08}.png", camera_id=camera_id))
    else:
        database(original)
    rows, observed = [], []
    for index in range(2):
        name = f"{index:08}.png"
        gray = np.full((100, 200), 128, dtype=np.uint8)
        mask = np.full_like(gray, 255)
        mask[:10] = 0
        assert cv.imwrite(str(prepared / "images" / name), gray)
        assert cv.imwrite(str(prepared / "masks" / (name + ".png")), mask)
        rows.append(dict(image="images/" + name))

    def extract(gray, mask, maximum):
        observed.append(mask.copy())
        return [cv.KeyPoint(float(30 + i), 40.0, 2.0) for i in range(24)], np.ones(
            (24, 128), dtype=np.float32
        )

    monkeypatch.setattr(learned_route_features, "extract_masked_sift", extract)
    monkeypatch.setattr(fused, "propose_pairs", lambda values: [])
    monkeypatch.setattr(
        fused,
        "verified_matches",
        lambda *args, **kwargs: (
            np.empty((0, 2), dtype=np.uint32),
            np.empty((0, 2), dtype=np.uint32),
        ),
    )
    before = hashlib.sha256(original.read_bytes()).hexdigest()
    fused._build_sift(prepared, original, output, rows, lambda: None, lambda *args: None)
    report = json.loads((output / "detector-masks.json").read_bytes())
    with sqlite3.connect(output / "sift.db") as db:
        assert db.execute(
            "SELECT type, rows, cols FROM descriptors ORDER BY image_id"
        ).fetchall() == [(0, 24, 128), (0, 24, 128)]
    if native_schema:
        with p.Database.open(output / "sift.db") as db:
            for image in db.read_all_images():
                descriptors = db.read_descriptors(image.image_id)
                assert descriptors.type == p.FeatureExtractorType.SIFT
                assert descriptors.data.shape == (24, 128)
    assert len(report["images"]) == 2 and len(observed) == 2
    for expected, record in zip(observed, report["images"]):
        effective = output / record["effective_mask"]["path"]
        assert np.array_equal(expected, cv.imread(str(effective), cv.IMREAD_GRAYSCALE))
        assert not expected[:10].any() and not expected[97:].any()
        assert (
            hashlib.sha256(effective.read_bytes()).hexdigest() == record["effective_mask"]["sha256"]
        )
        supplied = prepared / "masks" / (record["image"] + ".png")
        assert hashlib.sha256(supplied.read_bytes()).hexdigest() == record["supplied_mask_sha256"]
        assert cv.imread(str(supplied), cv.IMREAD_GRAYSCALE)[99].all()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == before


def test_too_many_views_are_rejected_before_any_workspace_or_model_load(tmp_path):
    with pytest.raises(ValueError, match="fused_view_quota"):
        fused.recover_fused(
            tmp_path, tmp_path, object(), 241, 0.0, 600.0, lambda: None, lambda *args: None
        )
    assert not (tmp_path / "fused-recovery").exists()


def orchestration(
    tmp_path,
    monkeypatch,
    *,
    admissible=True,
    fail_native=None,
    changed_k=False,
    matcher_backend=fused.BF_BACKEND,
):
    from scripts.pilot import reconstruct_route, route_native_track_policy

    job, prepared = source(tmp_path)
    binary = tmp_path / "colmap.exe"
    binary.write_bytes(b"pinned fixture binary")
    monkeypatch.setattr(fused, "COLMAP", binary)
    monkeypatch.setattr(fused, "COLMAP_SHA256", hashlib.sha256(binary.read_bytes()).hexdigest())

    def make_model(name):
        def write(path):
            for filename in ("cameras.bin", "images.bin", "points3D.bin"):
                (path / filename).write_bytes((name + filename).encode())

        return SimpleNamespace(
            name=name,
            points3D={i: object() for i in range(400)},
            write=write,
            update_point_3d_errors=lambda: None,
        )

    baseline, candidate = make_model("baseline"), make_model("candidate")
    post = make_model("post") if changed_k else candidate
    monkeypatch.setitem(
        sys.modules,
        "pycolmap",
        SimpleNamespace(
            __version__="4.2.1",
            Reconstruction=lambda path: post if Path(path).name == "ba-model" else candidate,
        ),
    )

    def build(prepared, _db, output, rows, check, progress, **_kwargs):
        (output / "sift.db").write_bytes(b"owned measured descriptors")
        (output / "sift-features").mkdir()
        (output / "detector-masks.json").write_text(
            json.dumps(dict(images=[dict(image=Path(row["image"]).name) for row in rows]))
        )
        return output / "sift.db", [], []

    monkeypatch.setattr(fused, "_build_sift", build)

    def fuse(_first, _second, output, **kwargs):
        namespace = dict(
            source_sift_database_sha256=hashlib.sha256(
                (output / "sift.db").read_bytes()
            ).hexdigest(),
            images=[
                dict(videoImageId=i + 1, name=Path(row["image"]).name)
                for i, row in enumerate(
                    json.loads((prepared / "reconstruction-input.json").read_text())["images"]
                )
            ],
        )
        with sqlite3.connect(output / "database.db") as db:
            db.execute("CREATE TABLE matches(pair_id INTEGER)")
        (output / "namespace.json").write_text(json.dumps(namespace))
        np.savez_compressed(output / "row-remapping.npz", sift_1=np.array([1]))
        return namespace

    monkeypatch.setattr(fused, "fuse_databases", fuse)
    monkeypatch.setattr(
        fused, "_seal_database", lambda path: None
    )  # This orchestration fixture uses byte stubs; real SQLite sealing is tested above.
    monkeypatch.setattr(fused, "audit_heldouts", lambda *args, **kwargs: dict(pairs=[]))
    monkeypatch.setattr(
        route_native_track_policy,
        "filter_whole_tracks",
        lambda *args, **kwargs: dict(removed_count=0),
    )
    monkeypatch.setattr(
        route_native_track_policy, "audit_native_model", lambda *args, **kwargs: dict(passed=True)
    )
    monkeypatch.setattr(
        route_native_track_policy,
        "measurement_signature",
        lambda rec, **kwargs: dict(cameras=rec.name if changed_k else "unchanged-K"),
    )

    def assess(rec, *args, **kwargs):
        report = dict(
            route_admissible=admissible and rec is not baseline,
            scene_admissible=True,
            coverage=1.0,
            registered=14,
            reprojection_px=1.0,
            points=400,
            execution_qualified=False,
        )
        return dict(source_manifest_sha256="fixture"), report

    monkeypatch.setattr(reconstruct_route, "model_assessment", assess)
    calls = []

    def native(arguments, output, label, maximum, check):
        check()
        calls.append((label, arguments, maximum))
        if label == fail_native:
            raise RuntimeError("fused_native_timeout")
        if label == "global-map":
            model = output / "models/0"
            model.mkdir()
            (model / "cameras.bin").write_bytes(b"candidate")
        if label == "fixed-k-ba":
            (output / "ba-model").mkdir()
        return dict(exit_code=0)

    def run():
        return fused.recover_fused(
            job,
            prepared,
            baseline,
            14,
            0.0,
            6.5,
            lambda: None,
            lambda *args: None,
            native_runner=native,
            matcher_backend=matcher_backend,
        )

    return job, prepared, baseline, candidate, calls, run


def test_successful_engine_uses_existing_admission_and_seals_native_bundle_without_source_video_copy(
    tmp_path, monkeypatch
):
    job, prepared, baseline, candidate, calls, run = orchestration(tmp_path, monkeypatch)
    chosen, report = run()
    assert chosen is candidate and chosen is not baseline and report["accepted"]
    assert report["source_modified"] is False and report["execution_qualified"] is False
    assert [row[0] for row in calls] == ["verify", "calibrate", "global-map", "fixed-k-ba"]
    global_arguments = [str(v) for v in calls[2][1]]
    assert global_arguments[global_arguments.index("--GlobalMapper.gp_use_gpu") + 1] == "0"
    assert global_arguments[global_arguments.index("--GlobalMapper.ba_ceres_use_gpu") + 1] == "0"
    assert global_arguments[global_arguments.index("--image_path") + 1] == str(prepared / "images")
    assert not (prepared / "fused-recovery/video.h264").exists()
    assert report["model_sha256"].keys() == {"cameras.bin", "images.bin", "points3D.bin"}
    assert (
        report["source_manifest_sha256"]
        == hashlib.sha256((job / "input/manifest.json").read_bytes()).hexdigest()
    )
    for asset in report["assets"].values():
        assert (
            hashlib.sha256((prepared / "fused-recovery" / asset["path"]).read_bytes()).hexdigest()
            == asset["sha256"]
        )
    masks = json.loads((prepared / "fused-recovery/detector-masks.json").read_bytes())
    assert masks["source_manifest_sha256"] == report["source_manifest_sha256"]
    assert masks["declared_profile"] == dict(
        mode="walking", hudProfile=None, hud_hidden_declared=None
    )
    assert masks["supplied_mask_producer"] == "unknown_hash_bound_pixels"
    assert masks["detector_footer_exclusion_y"] == 0.975
    assert len(masks["producer_sources"]) == 5
    assert report["intrinsics_prior"]["applied"] is False
    assert report["intrinsics_prior"]["physical_calibration_verified"] is False
    assert (
        global_arguments[global_arguments.index("--GlobalMapper.ba_refine_focal_length") + 1] == "1"
    )
    boundaries = json.loads((prepared / "fused-recovery/database-boundaries.json").read_bytes())[
        "boundaries"
    ]
    assert [row["stage"] for row in boundaries] == [
        "before_verify",
        "before_calibrate",
        "before_global_map",
        "after_global_map",
        "final_bundle",
    ]
    assert all(
        row["wal_bytes"] == 0 and row["owned_sqlite_handles_explicitly_closed"]
        for row in boundaries
    )


@pytest.mark.parametrize(
    "backend,applied,skipped",
    [
        (fused.LIGHTGLUE_BACKEND, True, True),
        (fused.LIGHTGLUE_BACKEND, False, False),
        (fused.LIGHTGLUE_BACKEND, 1, False),
        (fused.LIGHTGLUE_BACKEND, "true", False),
        (fused.BF_BACKEND, True, False),
        (fused.BF_BACKEND, False, False),
    ],
)
def test_optional_calibrator_requires_only_new_matcher_and_exact_validated_prior(
    tmp_path, monkeypatch, backend, applied, skipped
):
    from scripts.pilot import route_intrinsics_prior

    _, prepared, _, candidate, calls, run = orchestration(
        tmp_path, monkeypatch, matcher_backend=backend
    )
    seeded = []

    def initialize(database, *_args, **_kwargs):
        # An observable DB marker proves verification runs after initialization,
        # rather than merely checking two calls somewhere in the same fixture.
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA user_version=17")
        seeded.append(True)
        return dict(applied=applied, physical_calibration_verified=False)

    monkeypatch.setattr(route_intrinsics_prior, "initialize_intrinsics", initialize)
    original_boundary = fused._native_database_boundary

    def boundary(folder, stage, check):
        if stage == "before_verify":
            assert seeded == [True]
            with closing(sqlite3.connect(folder / "database.db")) as connection:
                assert connection.execute("PRAGMA user_version").fetchone() == (17,)
        return original_boundary(folder, stage, check)

    monkeypatch.setattr(fused, "_native_database_boundary", boundary)
    chosen, report = run()
    assert chosen is candidate and report["accepted"]
    assert [row[0] for row in calls] == (
        ["verify", "global-map", "fixed-k-ba"]
        if skipped
        else ["verify", "calibrate", "global-map", "fixed-k-ba"]
    )
    calibration = json.loads((prepared / "fused-recovery/calibration.json").read_bytes())
    assert calibration == report["calibration"]
    assert calibration["skipped"] is skipped
    assert calibration["status"] == ("skipped" if skipped else "completed")
    assert calibration["native_verification_completed"] is True
    assert calibration["same_source_numeric_prior_applied"] is (applied is True)
    assert calibration["physical_calibration_verified"] is False
    assert calibration["global_focal_refinement"] is True
    assert (
        calibration["producer_sha256"]
        == hashlib.sha256(Path(fused.__file__).read_bytes()).hexdigest()
    )
    if skipped:
        assert calibration["reason"] == "valid_same_source_numeric_prior"
    intent = json.loads((prepared / "fused-recovery/intent.json").read_bytes())
    assert intent["calibration_policy"] == report["calibration_policy"]
    global_arguments = [str(v) for row in calls if row[0] == "global-map" for v in row[1]]
    assert (
        global_arguments[global_arguments.index("--GlobalMapper.ba_refine_focal_length") + 1] == "1"
    )


def test_canonical_frozen_copy_requires_exact_current_native_identity(tmp_path, monkeypatch):
    from scripts.pilot import route_native_track_policy

    job, prepared, _baseline, candidate, _calls, run = orchestration(tmp_path, monkeypatch)
    _chosen, report = run()
    target = prepared / "sparse/0"
    target.mkdir(parents=True)
    monkeypatch.setattr(
        route_native_track_policy, "native_identity_signature", lambda value, **kwargs: value.name
    )
    assert not fused.copy_frozen_model_if_current(
        job, prepared, SimpleNamespace(name="endpoint-repaired"), target, loader=lambda _: candidate
    )
    assert not list(target.iterdir())
    assert fused.copy_frozen_model_if_current(
        job, prepared, candidate, target, loader=lambda _: candidate
    )
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in target.iterdir()
    } == report["model_sha256"]
    assert not fused.copy_frozen_model_if_current(
        job, prepared, candidate, target, loader=lambda _: candidate
    )


def test_optional_database_failure_keeps_baseline_and_failed_attempt_receipt(tmp_path, monkeypatch):
    job, prepared, baseline, _candidate, _calls, run = orchestration(tmp_path, monkeypatch)

    def failed_database(*args, **kwargs):
        raise sqlite3.OperationalError("schema mismatch")

    monkeypatch.setattr(fused, "_build_sift", failed_database)
    chosen, report = run()
    assert chosen is baseline and report["reason"] == "fused_database_error"
    assert report["source_modified"] is False and not report["accepted"]
    assert (
        json.loads((prepared / "fused-recovery/result.json").read_bytes())["error_type"]
        == "OperationalError"
    )


@pytest.mark.parametrize("kind", ["seal", "descriptor_hash", "cancel_after_accept"])
def test_late_bundle_failure_cannot_leave_accepted_true_after_returning_baseline(
    tmp_path, monkeypatch, kind
):
    job, prepared, baseline, _candidate, _calls, run = orchestration(tmp_path, monkeypatch)
    if kind in {"seal", "cancel_after_accept"}:

        def failed_seal(path):
            if Path(path).name == "sift.db":
                raise (
                    RuntimeError("cancelled")
                    if kind == "cancel_after_accept"
                    else ValueError("fused_database_not_sealed")
                )

        monkeypatch.setattr(fused, "_seal_database", failed_seal)
    else:
        actual = fused._hash
        monkeypatch.setattr(
            fused,
            "_hash",
            lambda path, *args: "a" * 64 if Path(path).name == "sift.db" else actual(path, *args),
        )
    if kind == "cancel_after_accept":
        with pytest.raises(RuntimeError, match="cancelled"):
            run()
    else:
        chosen, report = run()
        assert chosen is baseline and report["accepted"] is False
    saved = json.loads((prepared / "fused-recovery/result.json").read_bytes())
    assert saved["accepted"] is False and saved["execution_qualified"] is False


@pytest.mark.parametrize("kind", ["incomplete", "native_timeout", "changed_intrinsics"])
def test_failed_candidate_cannot_replace_baseline_and_records_its_single_attempt(
    tmp_path, monkeypatch, kind
):
    job, prepared, baseline, _candidate, _calls, run = orchestration(
        tmp_path,
        monkeypatch,
        admissible=kind != "incomplete",
        fail_native="global-map" if kind == "native_timeout" else None,
        changed_k=kind == "changed_intrinsics",
    )
    original = (job / "input/manifest.json").read_bytes()
    chosen, report = run()
    assert chosen is baseline and report["accepted"] is False
    assert report["source_modified"] is False
    assert (prepared / "fused-recovery/result.json").exists()
    assert (job / "input/manifest.json").read_bytes() == original


def test_native_runner_terminates_only_its_owned_tree_on_memory_refusal_and_keeps_receipt(
    tmp_path, monkeypatch
):
    events = []

    class Process:
        pid = 123
        returncode = None
        ownership = dict(policy="owned-fixture", ownsDescendants=True)

        def poll(self):
            return self.returncode

        def stop(self):
            events.append("stop")
            self.returncode = -9

        def close(self):
            events.append("close")

        def wait(self, timeout):
            events.append(("wait", timeout))

    monkeypatch.setattr(fused, "spawn_owned", lambda *args, **kwargs: Process())
    monkeypatch.setattr(fused, "_child_affinity", lambda pid: events.append(("affinity", pid)))
    monkeypatch.setattr(fused, "_process_bytes", lambda _process: 2 * 1024**3)
    with pytest.raises(RuntimeError, match="fused_child_memory_quota"):
        fused.run_native(["owned-fixture"], tmp_path, "memory", 10, lambda: None)
    assert events == [("affinity", 123), "stop", "close", ("wait", 10)]
    receipt = json.loads((tmp_path / "memory-receipt.json").read_text())
    assert receipt["status"] == "failed" and receipt["reason"] == "fused_child_memory_quota"
    assert receipt["peak_sampled_process_bytes"] == 2 * 1024**3


def test_physical_holdout_aliases_are_excluded_only_from_evaluation(tmp_path):
    video, sift, out = tmp_path / "video.db", tmp_path / "sift.db", tmp_path / "out"
    database(video)
    database(sift, sift=True)
    out.mkdir()
    fused.fuse_databases(video, sift, out)
    before = (out / "database.db").read_bytes()
    # Original SIFT row1 aliases row0. Thus (row1,row2) aliases an actual
    # training match even though the row indices themselves are disjoint.
    heldouts = [dict(first=1, second=3, rows=[[1, 2], [2, 2], [2, 2]])]
    report = fused.audit_heldouts(
        out, heldouts, SimpleNamespace(reg_image_ids=lambda: [], images={})
    )
    assert report["pairs"][0]["proposed"] == 3
    assert report["pairs"][0]["physical_aliases_excluded"] == 2
    assert report["pairs"][0]["clean"] == 1
    assert report["admission_effect"] == "none" and not report["fit_used_heldout"]
    assert (out / "database.db").read_bytes() == before
