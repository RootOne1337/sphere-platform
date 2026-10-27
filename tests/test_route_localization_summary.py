import copy

import pytest

from scripts.pilot.summarize_route_localization import summarize


@pytest.fixture
def data():
    route = dict(id='route', source_capture_sha256='capture', source_seconds=[0., 1., 2., 4., 8.])
    samples = [
        dict(source_index=1, media_seconds=.2, pose=dict(state='unknown', reason='route_pose_not_verified', segment=None)),
        dict(source_index=2, media_seconds=1.5, pose=dict(state='confirming', reason='not_clearance', segment=1)),
        dict(source_index=3, media_seconds=3., pose=dict(state='localized', reason='not_clearance', segment=0)),
    ]
    report = dict(schema='sphere-route-localization-quality-v1', same_capture=True,
                  capture_manifest_sha256='capture', route_id='route', physical_actions=0,
                  execution_qualified=False, samples=samples)
    return report, route


def test_summary_distinguishes_unverified_poses_from_recording_time_sanity(data):
    result = summarize(*data)
    assert result['counts'] == dict(unknown=1, confirming=1, localized=1)
    assert result['unknown_reasons'] == {'route_pose_not_verified': 1}
    assert result['timestamp_sanity']['median_seconds'] == 1.
    assert result['timestamp_sanity']['maximum_seconds'] == 2.
    assert result['timestamp_sanity']['over_2_seconds'] == 0
    assert result['timing_is_not_position_ground_truth'] is True
    assert result['execution_qualified'] is False


@pytest.mark.parametrize('change', ['capture', 'route', 'independent', 'out_of_order', 'unknown_segment'])
def test_summary_rejects_inconsistent_identity_or_samples(data, change):
    report, route = copy.deepcopy(data)
    if change == 'capture':
        report['capture_manifest_sha256'] = 'other'
    elif change == 'route':
        report['route_id'] = 'other'
    elif change == 'independent':
        report['same_capture'] = False
    elif change == 'out_of_order':
        report['samples'][2]['media_seconds'] = .1
    else:
        report['samples'][0]['pose']['segment'] = 1
    with pytest.raises(ValueError):
        summarize(report, route)
