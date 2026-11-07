"""Optional learned matching preserves measured rows and never consumes holdouts."""

import builtins
import hashlib
import sqlite3
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import cv2 as cv
import numpy as np
import pytest

from scripts.pilot import learned_route_features as pinned
from scripts.pilot import route_fused_recovery as fused
from scripts.pilot import route_lightglue_matcher as learned


def features(count=64):
    rng = np.random.default_rng(7)
    desc = rng.uniform(0.01, 1, (count, 128)).astype(np.float32)
    desc /= np.linalg.norm(desc, axis=1, keepdims=True)
    geometry = np.c_[
        np.arange(count) % 8 * 12 + 0.5,
        np.arange(count) // 8 * 6 + 0.5,
        np.full(count, 3.25),
        np.full(count, 0.75),
    ].astype("<f4")
    return geometry, desc


def test_payloads_retain_old_xy_scale_radians_and_distinct_descriptor_families():
    geometry, desc = features()
    before = geometry.tobytes(), desc.tobytes()
    temporal = learned.feature_payload(geometry, desc, (128, 64))
    loop = learned.feature_payload(geometry, desc, (128, 64), loop=True)
    np.testing.assert_array_equal(temporal.keypoints, geometry[:, :2])
    np.testing.assert_array_equal(temporal.scales, geometry[:, 2])
    np.testing.assert_array_equal(temporal.oris, geometry[:, 3])
    np.testing.assert_array_equal(temporal.image_size, [128, 64])
    np.testing.assert_array_equal(temporal.descriptors, desc)
    native = np.clip(np.round(desc * 512), 0, 255).astype(np.uint8)
    decoded = native.astype(np.float32)
    decoded /= np.maximum(np.linalg.norm(decoded, axis=1, keepdims=True), 1e-6)
    np.testing.assert_array_equal(loop.descriptors, decoded)
    assert not np.array_equal(loop.descriptors, temporal.descriptors)
    assert loop.native_descriptors_sha256 == hashlib.sha256(native.tobytes()).hexdigest()
    assert temporal.geometry_sha256 == loop.geometry_sha256
    assert before == (geometry.tobytes(), desc.tobytes())


@pytest.mark.parametrize("threads", [True, 0, 5, 2.0, "2"])
def test_loader_thread_configuration_is_validated_before_optional_import(tmp_path, threads):
    with pytest.raises(ValueError, match="matching_threads"):
        pinned.load_matcher(tmp_path, device="cpu", num_threads=threads)


def test_missing_assets_fail_before_importing_torch(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name == "torch":
            raise AssertionError("optional tensor runtime imported before verified assets")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    with pytest.raises(RuntimeError, match="weights_mismatch"):
        learned.LocalLightGlueMatcher(tmp_path, device="cpu")


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)
        self.device = "cpu"

    def __getitem__(self, key):
        return Tensor(self.value[key])

    def to(self, device):
        self.device = device
        return self

    def cpu(self):
        return self

    def numpy(self):
        return self.value


def fake_runtime(tmp_path, monkeypatch, *, invalid=False):
    calls, payloads = [], []
    state = dict(threads=4, interop=4)
    torch = SimpleNamespace(
        __version__="fixture-no-native-inference",
        set_num_threads=lambda n: state.update(threads=n),
        get_num_threads=lambda: state["threads"],
        set_num_interop_threads=lambda n: state.update(interop=n),
        get_num_interop_threads=lambda: state["interop"],
        manual_seed=lambda _: None,
        from_numpy=Tensor,
        inference_mode=nullcontext,
        cuda=SimpleNamespace(empty_cache=lambda: None),
    )
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setattr(
        pinned, "validate_assets", lambda root: (tmp_path / "source", tmp_path / "weights")
    )

    def loader(root, fraction, *, device, num_threads):
        calls.append(dict(device=device, num_threads=num_threads, fraction=fraction))

        def run(data):
            payloads.append(data)
            count = len(data["image0"]["keypoints"].value[0])
            matched = np.c_[np.arange(count), np.arange(count)]
            if invalid:
                matched[0, 0] = count
            return {"matches": Tensor(matched[None])}

        return run

    monkeypatch.setattr(pinned, "load_matcher", loader)
    return calls, payloads


def test_matcher_is_lazy_explicit_cached_and_binds_exact_input_rows(tmp_path, monkeypatch):
    calls, payloads = fake_runtime(tmp_path, monkeypatch)
    geometry, desc = features()
    with learned.LocalLightGlueMatcher(tmp_path, device="cuda", loop_device="cuda") as matcher:
        matcher.register(10, geometry, desc, (128, 64))
        matcher.register(30, geometry, desc, (128, 64))
        assert calls == []
        first = matcher.match(10, 30, kind="temporal")
        matcher.match(10, 30, kind="appearance_loop_proposal")
        assert calls == [dict(device="cuda", num_threads=2, fraction=0.20)]
        assert first.tolist() == [[i, i] for i in range(64)]
        assert set(payloads[0]["image0"]) == {
            "keypoints",
            "scales",
            "oris",
            "descriptors",
            "image_size",
        }
        np.testing.assert_array_equal(payloads[0]["image0"]["keypoints"].value[0], geometry[:, :2])
        assert not np.array_equal(
            payloads[0]["image0"]["descriptors"].value, payloads[1]["image0"]["descriptors"].value
        )
        proof = matcher.receipt()
        assert proof["historical_loop_device_changed"] and proof["torch_threads"] == 2
        assert proof["torch_interop_threads"] == 1 and proof["matched_pairs"] == 2
        assert proof["weights_sha256"] == pinned.WEIGHTS and not proof["bf_fallback"]
        assert not proof["execution_qualified"]
    assert matcher.closed and not matcher.tensor_cache and not matcher.matchers


def test_invalid_output_has_no_fallback_and_scope_closes(tmp_path, monkeypatch):
    fake_runtime(tmp_path, monkeypatch, invalid=True)
    geometry, desc = features()
    matcher = learned.LocalLightGlueMatcher(tmp_path, device="cpu")
    with pytest.raises(RuntimeError, match="output_invalid"), matcher:
        matcher.register(1, geometry, desc, (128, 64))
        matcher.register(2, geometry, desc, (128, 64))
        matcher.match(1, 2, kind="temporal")
    assert matcher.closed


def test_deadline_and_pair_quota_are_not_waived(tmp_path, monkeypatch):
    fake_runtime(tmp_path, monkeypatch)
    now = [0.0]
    with learned.LocalLightGlueMatcher(
        tmp_path, device="cpu", clock=lambda: now[0], max_seconds=1
    ) as matcher:
        now[0] = 2.0
        with pytest.raises(RuntimeError, match="timeout"):
            matcher.register(1, *features(), (128, 64))


def test_hud_cannot_change_new_world_signature_but_default_bf_is_unchanged():
    rng = np.random.default_rng(3)
    image = rng.integers(0, 256, (108, 192), np.uint8)
    mask = np.zeros_like(image)
    mask[20:90, 40:150] = 255
    changed = image.copy()
    changed[mask == 0] = 255 - changed[mask == 0]
    np.testing.assert_array_equal(
        learned.masked_coarse_signature(image, mask), learned.masked_coarse_signature(changed, mask)
    )
    assert not np.array_equal(fused.coarse_signature(image), fused.coarse_signature(changed))
    assert np.isfinite(learned.masked_coarse_signature(image, np.zeros_like(mask))).all()


def test_generic_learned_loop_policy_is_deterministic_bounded_and_not_endpoint_hardcoded():
    values = np.ones((173, 576), np.float32) / np.sqrt(576)
    times = [i * 0.2 for i in range(173)]
    proposed = learned.propose_learned_pairs(values, times)
    assert proposed == learned.propose_learned_pairs(values, times)
    temporal = [p for p in proposed if p[2] == "temporal"]
    loops = [p for p in proposed if p[2] != "temporal"]
    assert len(temporal) == 846 and len(loops) == 32
    assert all(b - a in fused.TEMPORAL_LAGS for a, b, _ in temporal)
    assert all(b - a >= 16 for a, b, _ in loops)
    empty = learned.propose_learned_pairs(np.zeros_like(values), times)
    assert all(kind == "temporal" for _, _, kind in empty)


def test_learned_hash_holdouts_never_reach_fitting_or_training(tmp_path, monkeypatch):
    geometry, _ = features(96)
    xy = geometry[:, :2]
    rows = np.c_[np.arange(96), np.arange(96)].astype("<u4")
    expected = np.array([hashlib.sha256(f"{a}:{b}".encode()).digest()[0] >= 192 for a, b in rows])
    captured = []

    def fit(first, second, **kwargs):
        captured.append(first.copy())
        return np.array([[0.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]), np.ones(
            (len(first), 1), np.uint8
        )

    monkeypatch.setattr(cv, "findFundamentalMat", fit)
    accepted, held = fused.verified_correspondences(
        xy, xy, rows, holdout=True, holdout_policy="sha256_row_pair_byte192_v1"
    )
    np.testing.assert_array_equal(captured[0], xy[~expected] - 0.5)
    np.testing.assert_array_equal(held, rows[expected])
    assert not set(map(tuple, accepted)) & set(map(tuple, held))


def test_invalid_backend_arguments_refuse_before_optional_runtime_or_database_write(tmp_path):
    with pytest.raises(ValueError, match="matcher_configuration"):
        fused._build_sift(
            tmp_path,
            tmp_path / "absent.db",
            tmp_path / "out",
            [],
            lambda: None,
            lambda *args: None,
            matcher_backend=learned.BACKEND,
            matcher_device="other",
        )
    assert not (tmp_path / "out").exists()
    with pytest.raises(ValueError, match="matcher_configuration"):
        fused.recover_fused(
            tmp_path,
            tmp_path,
            None,
            10,
            0,
            1,
            lambda: None,
            lambda *args: None,
            matcher_backend="unknown",
        )


def test_learned_native_only_training_keeps_holdout_and_source_database_unchanged(
    tmp_path, monkeypatch
):
    prepared, output = tmp_path / "prepared", tmp_path / "candidate"
    prepared.mkdir()
    output.mkdir()
    source = prepared / "database.db"
    with sqlite3.connect(source) as db:
        db.executescript(
            "CREATE TABLE images(image_id INTEGER,name TEXT);CREATE TABLE matches(pair_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);CREATE TABLE two_view_geometries(pair_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);CREATE TABLE descriptors(image_id INTEGER,type INTEGER,rows INTEGER,cols INTEGER,data BLOB);CREATE TABLE keypoints(image_id INTEGER,rows INTEGER,cols INTEGER,data BLOB);"
        )
        db.executemany(
            "INSERT INTO images VALUES(?,?)", [(i + 1, f"{i:08}.png") for i in range(10)]
        )
    original_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    geometry, desc = features()
    keys = [
        cv.KeyPoint(float(x - 0.5), float(y - 0.5), float(s), float(np.degrees(a)))
        for x, y, s, a in geometry
    ]
    monkeypatch.setattr(pinned, "extract_masked_sift", lambda *args: (keys, desc.copy()))
    monkeypatch.setattr(cv, "imread", lambda *args: np.zeros((64, 128), np.uint8))
    monkeypatch.setattr(
        learned,
        "propose_learned_pairs",
        lambda *args: [(0, 1, "temporal"), (0, 9, "appearance_loop_proposal")],
    )
    events = []

    class Session:
        def __init__(self, *args, **kwargs):
            events.append(("configuration", kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            events.append("closed")

        def register(self, *args):
            pass

        def match(self, *args, **kwargs):
            matched = np.c_[np.arange(64), np.arange(64)].astype("<u4")
            if kwargs["kind"] != "temporal":
                matched = matched[
                    [
                        hashlib.sha256(f"{int(a)}:{int(b)}".encode()).digest()[0] >= 192
                        for a, b in matched
                    ]
                ]
            return matched

        def receipt(self):
            return dict(backend=learned.BACKEND, fixture=True)

    monkeypatch.setattr(learned, "LocalLightGlueMatcher", Session)

    def no_training_prefilter(*args, **kwargs):
        raise AssertionError("LG constraints must reach pinned native verification")

    monkeypatch.setattr(cv, "findFundamentalMat", no_training_prefilter)
    rows = [dict(image=f"images/{i:08}.png", relative_ticks_90k=i * 18000) for i in range(10)]
    database, pairs, held = fused._build_sift(
        prepared,
        source,
        output,
        rows,
        lambda: None,
        lambda *args: None,
        matcher_backend=learned.BACKEND,
        matcher_device="cuda",
        loop_matcher_device="cuda",
    )
    assert events[-1] == "closed" and len(pairs) == 1
    assert held[0]["first"] == 1 and held[0]["second"] == 10 and not held[0]["train_pair_written"]
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1
        assert db.execute("SELECT rows FROM matches").fetchone()[0] == 64
        assert db.execute("SELECT DISTINCT type FROM descriptors").fetchall() == [(0,)]
    assert original_sha == hashlib.sha256(source.read_bytes()).hexdigest()
    assert (output / "lightglue-matcher.json").is_file()
