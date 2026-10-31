import copy
import math

import pytest

from scripts.pilot.route_speed_consistency import analyze


def fixture(count=22):
    frames = [dict(index=i, relative_ticks_90k=i * 9000) for i in range(count)]
    samples = [dict(frame_index=i, relative_ticks_90k=i * 9000, hud_kmh=36.0, status='accepted') for i in range(count)]
    geometry = {'cameras': [dict(image=f'{i:08}.png', ticks_90k=i * 9000, center=[2.0*i, 0, 0]) for i in range(count)]}
    return geometry, samples, frames


def test_constant_speed_scale_and_inputs_unchanged():
    g, s, f = fixture(); before = copy.deepcopy((g, s, f))
    result = analyze(g, s, f)
    assert result['fit_edge_count'] == 21
    assert result['sfm_units_per_hud_distance'] == pytest.approx(2)
    assert all(e['classification'] == 'consistent_with_fit' for e in result['edges'])
    assert (g, s, f) == before


def test_unknown_cannot_bridge_even_with_accepted_neighbors():
    g, s, f = fixture()
    s[10].update(status='unknown', hud_kmh=None)
    result = analyze(g, s, f)
    assert [result['edges'][i]['status'] for i in (9, 10)] == ['unknown', 'unknown']
    assert result['sfm_units_per_hud_distance'] is None


def test_gap_cannot_bridge_and_zero_is_observed():
    g, s, f = fixture()
    s = [sample for i, sample in enumerate(s) if i != 10]
    result = analyze(g, s, f, max_gap_seconds=.15)
    assert result['edges'][9]['status'] == result['edges'][10]['status'] == 'unknown'
    g, s, f = fixture(); s[5]['hud_kmh'] = s[6]['hud_kmh'] = 0
    edge = analyze(g, s, f)['edges'][5]
    assert edge['status'] == 'zero_hud_distance' and edge['hud_distance'] == 0 and edge['implied_scale'] is None


@pytest.mark.parametrize('mutation', ['nan', 'nonmonotonic', 'binding', 'camera'])
def test_invalid_inputs_rejected(mutation):
    g, s, f = fixture()
    if mutation == 'nan': s[4]['hud_kmh'] = math.nan
    if mutation == 'nonmonotonic': s[4], s[5] = s[5], s[4]
    if mutation == 'binding': s[4]['relative_ticks_90k'] += 1
    if mutation == 'camera': g['cameras'][4]['ticks_90k'] += 1
    with pytest.raises(ValueError): analyze(g, s, f)


def test_trusted_subset_outlier():
    g, s, f = fixture(25)
    g['cameras'][22]['center'][0] += 12
    result = analyze(g, s, f, trusted_edges=range(20))
    assert result['fit_scope'] == 'caller_selected_trusted_subset'
    assert result['edges'][21]['classification'] == 'scale_outlier_review'
