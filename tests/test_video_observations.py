from unittest.mock import patch
import cv2
import numpy as np

from scripts.pilot.video_observations import track_source_points


def test_real_translation_keeps_measured_coordinates_and_identity_mask():
    rng=np.random.default_rng(818)
    old=rng.integers(0,256,(180,320),dtype=np.uint8)
    moved=cv2.warpAffine(old,np.float32([[1,0,2],[0,1,-1]]),(320,180))
    points=cv2.goodFeaturesToTrack(old,80,.02,10)
    found,good=track_source_points(old,moved,points,tolerance=.75)
    assert good.sum()>=40
    np.testing.assert_allclose(np.median(found[good]-points[good,0],axis=0),[2,-1],atol=.1)


def test_empty_lk_output_loses_tracks_instead_of_crashing_or_inventing_motion():
    gray=np.zeros((30,30),np.uint8);points=np.array([[10,10],[20,20]],np.float32)
    with patch('cv2.calcOpticalFlowPyrLK',return_value=(None,None,None)) as lk:
        _,good=track_source_points(gray,gray,points,tolerance=.75)
    assert not good.any() and lk.call_count==1


def test_nonfinite_lk_point_is_removed_before_backward_opencv_call():
    gray=np.zeros((30,30),np.uint8);points=np.array([[10,10],[20,20]],np.float32)
    outputs=[(np.array([[[float('nan'),0]],[[20,20]]],np.float32),np.ones((2,1),np.uint8),None),
             (points.reshape(-1,1,2),np.ones((2,1),np.uint8),None)]
    def flow(_first,_second,observed,*_args,**_kwargs):
        assert np.isfinite(observed).all()
        return outputs.pop(0)
    with patch('cv2.calcOpticalFlowPyrLK',side_effect=flow):
        _,good=track_source_points(gray,gray,points,tolerance=.75)
    assert good.tolist()==[False,True]
