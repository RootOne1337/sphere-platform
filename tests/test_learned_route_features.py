"""A partial or altered tool delivery cannot silently execute or fetch weights."""

import pytest

from scripts.pilot.learned_route_features import available, validate_assets, verify_pairs


def test_sharp_masked_overlay_cannot_spend_the_world_feature_quota():
    cv2=pytest.importorskip('cv2');np=pytest.importorskip('numpy')
    from scripts.pilot.learned_route_features import extract_masked_sift
    rng=np.random.default_rng(42)
    rgb=rng.integers(0,256,(600,1000),dtype=np.uint8)
    # High contrast excluded area versus weaker texture in the observed world.
    rgb[420:]=rng.integers(100,145,(180,1000),dtype=np.uint8)
    mask=np.zeros_like(rgb);mask[430:]=255
    before=rgb.copy()
    old,_=cv2.SIFT_create(nfeatures=1024,contrastThreshold=.0066667,edgeThreshold=10).detectAndCompute(rgb,mask)
    points,descriptors=extract_masked_sift(rgb,mask,1024)
    assert len(points)>max(40,len(old)*4)
    assert len(points)<=1024 and descriptors.shape==(len(points),128)
    assert all(mask[round(point.pt[1]),round(point.pt[0])]>0 for point in points)
    np.testing.assert_array_equal(rgb,before)


def test_invalid_matching_device_and_budget_fail_before_importing_optional_runtime(tmp_path):
    from scripts.pilot.learned_route_features import extract_and_match,load_matcher
    with pytest.raises(ValueError,match='feature_budget'):
        extract_and_match(tmp_path,tmp_path,tmp_path/'db',None,None,None,max_features=True)
    with pytest.raises(ValueError,match='matching_device'):
        load_matcher(tmp_path,device='other')


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
        assert options.filter_stationary_matches is True
        calls.append((database, pair_file))

    monkeypatch.setitem(sys.modules, 'pycolmap', SimpleNamespace(
        TwoViewGeometryOptions=lambda: SimpleNamespace(ransac=SimpleNamespace(num_threads=4)),
        verify_matches=native_contract))
    verify_pairs(tmp_path / 'database.db', tmp_path / 'pairs.txt', token,filter_stationary=True)
    assert calls == [(tmp_path / 'database.db', tmp_path / 'pairs.txt')]
