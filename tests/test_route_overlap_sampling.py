import unittest
from unittest.mock import patch
from scripts.pilot.route_overlap_sampling import select_overlaps, plan_pose_gaps, run


def source(n):
    return [{'index':i, 'relative_ticks_90k':i*3000} for i in range(n)]


def bindings(frames, indices):
    return [{'image':f'{i:08d}.png', 'source_index':i,
             'relative_ticks_90k':frames[i]['relative_ticks_90k']} for i in indices]


class PoseGapPlanningTests(unittest.TestCase):
    def test_actual_outlier_binding_selects_inner_real_frames(self):
        frames=source(501); initial=[0, 496, 500]
        # Verified source PTS and f603 report's flagged image, reduced to one interval.
        for index,tick in zip(range(496,501),[1785510,1790010,1794420,1797480,1805040]):
            frames[index]['relative_ticks_90k']=tick
        mapping=bindings(frames, initial)
        result=plan_pose_gaps(frames,initial,mapping,{'speed_outliers':[{'view':92,'image':'00000500.png','seconds':20.056}]})
        self.assertEqual(result['added_indices'],[497,498,499])
        self.assertEqual(result['intervals'][0]['status'],'planned_unverified')
        self.assertFalse(result['execution_qualified'])

    def test_image_names_are_not_interpreted_as_source_indices(self):
        frames=source(5); initial=[0,4]; mapping=bindings(frames,initial)
        mapping[-1]['image']='00000001.png'
        result=plan_pose_gaps(frames,initial,mapping,{'speed_outliers':[{'image':'00000001.png'}]})
        self.assertEqual(result['added_indices'],[1,2,3])

    def test_budget_and_nonuniform_ticks_are_deterministic(self):
        frames=source(14); frames[5]['relative_ticks_90k']=13000
        initial=[0,6,13]; mapping=bindings(frames,initial)
        flags={'speed_outliers':[{'image':'00000013.png'},{'image':'00000006.png'}]}
        result=plan_pose_gaps(frames,initial,mapping,flags,max_additions=2,max_selected=5)
        self.assertEqual(result,plan_pose_gaps(frames,initial,mapping,flags,max_additions=2,max_selected=5))
        self.assertEqual(len(result['added_indices']),2)
        self.assertTrue(all(0<i<6 for i in result['added_indices']))
        self.assertEqual(result['intervals'][1]['status'],'budget_unresolved')

    def test_adjacent_and_empty_flags_never_claim_repair(self):
        frames=source(3); initial=[0,1,2]; mapping=bindings(frames,initial)
        result=plan_pose_gaps(frames,initial,mapping,{'speed_outliers':[{'image':'00000001.png'}]})
        self.assertEqual(result['added_indices'],[])
        self.assertEqual(result['intervals'][0]['status'],'adjacent_unresolved')
        self.assertEqual(plan_pose_gaps(frames,initial,mapping,{'speed_outliers':[]})['intervals'],[])

    def test_invalid_binding_flags_indices_ticks_and_types_fail_closed(self):
        frames=source(5); initial=[0,4]; mapping=bindings(frames,initial)
        cases=[(frames,initial,[mapping[0],dict(mapping[1],relative_ticks_90k=1)],{'speed_outliers':[]}),
               (frames,initial,mapping,{'speed_outliers':[{'image':'missing'}]}),
               (frames,initial,mapping,{'speed_outliers':[{'image':'00000000.png'}]}),
               (frames,[0,True],mapping,{'speed_outliers':[]}),
               (frames,initial,mapping,{'speed_outliers':None})]
        badticks=source(5); badticks[2]['relative_ticks_90k']=badticks[1]['relative_ticks_90k']
        cases.append((badticks,initial,mapping,{'speed_outliers':[]}))
        for args in cases:
            with self.subTest(args=args), self.assertRaises(ValueError): plan_pose_gaps(*args)
        with self.assertRaises(ValueError):
            plan_pose_gaps(frames,initial,mapping,{'speed_outliers':[]},max_additions=True)


class OverlapSamplingTests(unittest.TestCase):
    def test_measures_only_real_indices_and_preserves_endpoints(self):
        frames=source(9);seen=[]
        def measure(a,b):
            seen.append((a,b));return {'detected':100,'stable':100 if b-a<=2 else 10}
        selected,report=select_overlaps(frames,[0,8],measure,lambda:None,maximum=9)
        self.assertEqual(selected,[0,2,4,6,8])
        self.assertTrue(all(0<=a<b<9 for a,b in seen))
        self.assertEqual(len(selected),len(set(selected)))
        self.assertTrue(all(r['supported'] for r in report['final']))
        self.assertTrue(all(r['first_ticks_90k']==frames[r['first_index']]['relative_ticks_90k'] for r in report['final']))

    def test_impossible_support_is_unresolved_at_adjacent_frames(self):
        selected,report=select_overlaps(source(4),[0,3],lambda a,b:{'detected':0,'stable':0},lambda:None,maximum=4)
        self.assertEqual(selected,[0,1,2,3])
        self.assertEqual(len(report['final']),3)
        self.assertTrue(all(not r['supported'] and r['unresolved_reason']=='adjacent_source_frames' for r in report['final']))
        self.assertIn('insufficient_detected_features',report['final'][0]['causes'])

    def test_budget_and_priority_are_deterministic(self):
        measure=lambda a,b:{'detected':100,'stable':0}
        a,report=select_overlaps(source(12),[0,4,11],measure,lambda:None,maximum=5)
        b,again=select_overlaps(source(12),[0,4,11],measure,lambda:None,maximum=5)
        self.assertEqual(a,b);self.assertEqual(report['additions'],again['additions'])
        self.assertEqual(report['additions'][0],{'index':7,'split':[4,11]})
        self.assertEqual(len(a),5)
        self.assertTrue(any(r['unresolved_reason']=='view_budget_exhausted' for r in report['final']))

    def test_invalid_inputs_do_not_get_silently_repaired(self):
        for initial in ([1,4],[0,0,4],[0,5]):
            with self.subTest(initial=initial),self.assertRaises(ValueError):
                select_overlaps(source(5),initial,lambda a,b:{'detected':1,'stable':1},lambda:None)
        with self.assertRaises(ValueError):
            select_overlaps(source(3),[0,2],lambda a,b:{'detected':1,'stable':2},lambda:None)

    def test_cancellation_propagates(self):
        calls=[]
        def cancelled():
            calls.append(1)
            if len(calls)>2:raise RuntimeError('cancelled')
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            select_overlaps(source(8),[0,7],lambda a,b:{'detected':100,'stable':0},cancelled)

    def test_invalid_quotas_and_timestamps_fail_before_measurement(self):
        measure=lambda *args:self.fail('invalid configuration must not measure frames')
        for options in ({'maximum':2.5},{'maximum':True},{'min_support':float('nan')},
                        {'min_support':True},{'min_retention':float('nan')},{'min_retention':True}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                select_overlaps(source(3),[0,2],measure,lambda:None,**options)
        frames=source(3);frames[1]['relative_ticks_90k']=0
        with self.assertRaises(ValueError):
            select_overlaps(frames,[0,2],measure,lambda:None)
        for timeout in (True,0,121,float('nan')):
            with self.subTest(timeout=timeout),self.assertRaises(ValueError):
                run('missing-input','missing-prepared','missing-output',timeout=timeout)

    def test_run_refuses_before_reading_when_memory_is_low(self):
        with patch('scripts.pilot.resource_guard.windows_memory',return_value={'availableRamBytes':1,'commitLimitBytes':100,'committedBytes':1}):
            with self.assertRaisesRegex(RuntimeError,'memory_guard'):
                run('missing-input','missing-prepared','missing-output')

    def test_run_refuses_when_commit_headroom_is_low(self):
        with patch('scripts.pilot.resource_guard.windows_memory',return_value={'availableRamBytes':10*1024**3,'commitLimitBytes':100,'committedBytes':1}):
            with self.assertRaisesRegex(RuntimeError,'memory_guard'):
                run('missing-input','missing-prepared','missing-output')

    def test_run_cancellation_precedes_source_access(self):
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            run('missing-input','missing-prepared','missing-output',cancellation=lambda:True)


if __name__=='__main__':unittest.main()
