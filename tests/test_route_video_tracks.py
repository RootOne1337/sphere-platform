from scripts.pilot.route_video_tracks import shared_track_pairs


def test_track_identity_survives_index_changes_but_not_a_lookalike_detection():
    assert shared_track_pairs([101,104,108],[108,101,999]).tolist()==[[0,1],[2,0]]


def test_lost_or_newly_detected_tracks_do_not_invent_correspondences():
    assert shared_track_pairs([1,2,3],[4,5,6]).shape==(0,2)
    assert shared_track_pairs([],[]).shape==(0,2)
