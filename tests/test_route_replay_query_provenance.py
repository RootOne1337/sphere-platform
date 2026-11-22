"""A duplicate video must not inflate independent repeat-pass evidence."""
from types import SimpleNamespace

import pytest

from scripts.pilot.check_route_full_replay import query_provenance,observation_timing


def capture(tmp_path, name, *, identity, video=b'original', geometry=(1920,1080)):
    root=tmp_path/name;root.mkdir();(root/'video.h264').write_bytes(video)
    (root/'manifest.json').write_text(identity)
    return SimpleNamespace(root=root,geometry=geometry,manifest={'id':identity})


def test_renamed_copied_video_keeps_reference_exclusion_and_is_not_independent(tmp_path):
    first=capture(tmp_path,'reference',identity='one')
    duplicate=capture(tmp_path,'renamed',identity='two')
    report,excluded=query_provenance(first,duplicate,[3,7,10])
    assert excluded=={3,7,10}
    assert report['relation']=='same_video_heldout'
    assert report['distinctCaptureFiles'] is False
    assert report['independentGameplayConfirmed'] is False


def test_other_video_uses_all_query_indices_but_does_not_invent_same_route_truth(tmp_path):
    first=capture(tmp_path,'reference',identity='one')
    other=capture(tmp_path,'other',identity='two',video=b'other recording')
    report,excluded=query_provenance(first,other,[3,7,10])
    assert excluded==set()
    assert report['distinctCaptureFiles'] is True
    assert report['sameRouteVerified'] is False
    assert report['independentGameplayConfirmed'] is False


def test_reused_capture_id_or_stretched_query_cannot_be_compared_silently(tmp_path):
    first=capture(tmp_path,'reference',identity='one')
    edited=capture(tmp_path,'edited',identity='one',video=b'changed')
    with pytest.raises(ValueError,match='capture_id_reused'):
        query_provenance(first,edited,[3])
    portrait=capture(tmp_path,'portrait',identity='two',video=b'portrait',geometry=(1080,1920))
    with pytest.raises(ValueError,match='aspect_mismatch'):
        query_provenance(first,portrait,[3])


def test_a_fast_http_reply_cannot_hide_an_expired_encoded_query():
    timing=observation_timing(10.,10.1,10.3)
    assert timing['replyMs']==pytest.approx(200)
    assert timing['queryAgeMs']==pytest.approx(300)
    assert timing['queryExpired'] is True
    with pytest.raises(ValueError,match='clock_invalid'):
        observation_timing(10.,9.9,10.1)
