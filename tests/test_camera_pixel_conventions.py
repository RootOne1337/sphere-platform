import numpy as np
import pytest

from scripts.pilot.camera_pixel_conventions import tracking_points_to_colmap,colmap_calibration_to_opencv


def test_resize_maps_pixel_cells_before_changing_origin_without_half_pixel_bias():
    points=np.array([[0.,0.],[479.5,269.5],[959.,539.]])
    source=tracking_points_to_colmap(points,(1920,1080),(960,540))
    np.testing.assert_allclose(source,[[1,1],[960,540],[1919,1079]])
    np.testing.assert_allclose(source*.5-.5,points)


def test_projected_rays_agree_after_resize_including_rounded_dimensions():
    original=np.array([[700,0,960],[0,700,540],[0,0,1.]],float)
    before=original.copy()
    xyz=np.array([[-2,1,10],[1,-2,8],[0,0,5]],float)
    for source,target in [((1920,1080),(960,540)),((1919,1079),(960,540)),((960,540),(960,540))]:
        expected=xyz@original.T;expected=expected[:,:2]/expected[:,2:]
        expected=expected*(np.array(target)/source)-.5
        converted=colmap_calibration_to_opencv(original,source,target)
        projected=xyz@converted.T;projected=projected[:,:2]/projected[:,2:]
        np.testing.assert_allclose(projected,expected)
    np.testing.assert_array_equal(original,before)


def test_invalid_geometry_and_nonfinite_coordinates_are_refused():
    for bad in ((True,540),(0,540),(960,),(-1,540)):
        with pytest.raises(ValueError,match='pixel_transform_geometry'):
            tracking_points_to_colmap([[0,0]],bad,(960,540))
    with pytest.raises(ValueError,match='pixel_transform_points'):
        tracking_points_to_colmap([[float('nan'),0]],(960,540),(960,540))
    with pytest.raises(ValueError,match='pixel_transform_calibration'):
        colmap_calibration_to_opencv(np.zeros((3,3)),(960,540),(960,540))
