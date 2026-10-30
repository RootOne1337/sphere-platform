"""A partial or altered tool delivery cannot silently execute or fetch weights."""

import pytest

from scripts.pilot.learned_route_features import available, validate_assets, verify_pairs


def test_missing_optional_delivery_is_detected_without_importing_torch(tmp_path):
    assert not available(tmp_path)
    with pytest.raises(RuntimeError, match='weights_mismatch'):
        validate_assets(tmp_path)


def test_damaged_checkpoint_is_refused_before_source_execution(tmp_path):
    tools = tmp_path / '.local-pilot/reconstruction-tools'
    script = tools / 'lightglue/lightglue/lightglue.py'
    script.parent.mkdir(parents=True)
    script.write_text('raise AssertionError("must never run")')
    weights = tools / 'lightglue-models/hub/checkpoints/sift_lightglue_v0-1_arxiv.pth'
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b'not-an-official-checkpoint')
    assert available(tmp_path)
    with pytest.raises(RuntimeError, match='weights_mismatch'):
        validate_assets(tmp_path)


def test_native_pair_verifier_receives_supported_parallelism_and_cancellation(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    token = object()
    calls = []

    def native_contract(database, pair_file, *, options, cancellation_token):
        # The real COLMAP boundary rejects nested parallel RANSAC before work.
        if options.ransac.num_threads != 1:
            raise ValueError('Parallel RANSAC is not supported inside multi-threaded matching')
        assert cancellation_token is token
        calls.append((database, pair_file))

    monkeypatch.setitem(sys.modules, 'pycolmap', SimpleNamespace(
        TwoViewGeometryOptions=lambda: SimpleNamespace(ransac=SimpleNamespace(num_threads=4)),
        verify_matches=native_contract))
    verify_pairs(tmp_path / 'database.db', tmp_path / 'pairs.txt', token)
    assert calls == [(tmp_path / 'database.db', tmp_path / 'pairs.txt')]
