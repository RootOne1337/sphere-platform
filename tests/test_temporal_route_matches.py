import numpy as np
import pytest

from scripts.pilot.temporal_route_matches import flow_supported_matches


def test_repeated_window_match_requires_continuous_track_endpoint():
    proposals=np.array([[4,0],[4,1],[7,2],[8,3]],dtype=np.uint32)
    source_ids=np.array([4,7,8])
    tracked=np.array([[10.,20.],[40.,50.],[70.,80.]])
    # The second, visually similar window is 30 tracking pixels away.
    destinations=np.array([[20.5,40.5],[80.5,40.5],[80.5,100.5],[140.5,160.5]])
    kept=flow_supported_matches(proposals,source_ids,tracked,np.array([True,True,False]),destinations,scale=.5)
    assert kept.tolist()==[[4,0],[7,2]]
    assert proposals.tolist()==[[4,0],[4,1],[7,2],[8,3]]


def test_missing_track_is_not_substituted_by_a_nearby_identity():
    proposals=np.array([[999,0],[4,1]],dtype=np.uint32)
    destination=np.array([[10.5,20.5],[10.5,20.5]])
    assert flow_supported_matches(proposals,np.array([4]),np.array([[10.,20.]]),np.array([True]),destination,scale=1.).tolist()==[[4,1]]
    with pytest.raises(ValueError,match='temporal_match_feature_index'):
        flow_supported_matches([[4,7]],np.array([4]),np.array([[10.,20.]]),np.array([True]),destination,scale=1.)
