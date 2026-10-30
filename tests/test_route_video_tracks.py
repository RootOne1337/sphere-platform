from scripts.pilot.route_video_tracks import shared_track_pairs


def test_track_identity_survives_index_changes_but_not_a_lookalike_detection():
    assert shared_track_pairs([101,104,108],[108,101,999]).tolist()==[[0,1],[2,0]]


def test_lost_or_newly_detected_tracks_do_not_invent_correspondences():
    assert shared_track_pairs([1,2,3],[4,5,6]).shape==(0,2)
    assert shared_track_pairs([],[]).shape==(0,2)


def test_recording_gap_starts_new_identities_even_when_images_look_identical(tmp_path,monkeypatch):
    import hashlib,json,sqlite3,sys
    from types import SimpleNamespace
    import numpy as np
    import pytest
    av=pytest.importorskip('av')
    from scripts.pilot.route_video_tracks import build_video_track_database

    (tmp_path/'input').mkdir();(tmp_path/'input/manifest.json').write_bytes(b'{}')
    (tmp_path/'control.json').write_text('{"mask":"none"}')
    prepared=tmp_path/'prepared';prepared.mkdir()
    rows=[dict(source_index=i,image=f'{i:08}.png',relative_ticks_90k=i*3000+(27000 if i>=6 else 0)) for i in range(12)]
    provenance=dict(source_manifest_sha256=hashlib.sha256(b'{}').hexdigest(),images=rows)
    (prepared/'reconstruction-input.json').write_text(json.dumps(provenance))
    database=prepared/'source.db'
    with sqlite3.connect(database):pass
    written=[]
    class DB:
        def __enter__(self):return self
        def __exit__(self,*_):pass
        def read_all_images(self):return [SimpleNamespace(name=row['image'],image_id=i+1) for i,row in enumerate(rows)]
        def clear_keypoints(self):pass
        def clear_descriptors(self):pass
        def clear_matches(self):pass
        def clear_two_view_geometries(self):pass
        def write_keypoints(self,*_):pass
        def write_matches(self,a,b,_):written.append((a,b))
    monkeypatch.setitem(sys.modules,'pycolmap',SimpleNamespace(Database=SimpleNamespace(open=lambda _:DB())))
    from motor_worker import browser_teach
    monkeypatch.setattr(browser_teach,'validate_browser',lambda _:SimpleNamespace(geometry=(320,180),frames=rows))
    gray=np.random.default_rng(819).integers(0,256,(180,320),dtype=np.uint8)
    monkeypatch.setattr(browser_teach,'decoded_browser',lambda _:iter((dict(index=i,relative_ticks_90k=row['relative_ticks_90k']),av.VideoFrame.from_ndarray(gray,format='gray')) for i,row in enumerate(rows)))
    report=build_video_track_database(tmp_path,prepared,database,prepared/'output.db',lambda:None)
    assert any(a<=6 and b<=6 for a,b in written) and any(a>=7 and b>=7 for a,b in written)
    assert not any(a<=6 and b>=7 for a,b in written)
    assert report['trackingBreaks'][0]['sourceIndex']==6
    assert (tmp_path/'input/manifest.json').read_bytes()==b'{}'
