import copy
import json
import tempfile
import unittest
from pathlib import Path

from scripts.pilot.route_walk_reports import store_walk_report


class WalkReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.job = Path(self.tmp.name)
        self.body = dict(schema='sphere-walk-summary-v1', id='a'*32, clip='b'*32, release='closed',
            stopReason='contact_video_stale', inputFailure='contact_video_stale', stopFrameAgeMs=281.7,
            stopFrameSequence=1472, executionQualified=False, inputSummary=dict(submitted=2, applied=2, events=9),
            stages=[dict(stage='source_gap', elapsedMs=900, durationMs=280, sequence=1469)],
            observations=[dict(elapsedMs=800, sequence=1469, ageMs=38.8, computeMs=8.3,
                state='following', reason='walk_camera_relative_pursuit', poseState='localized', inliers=194, progress=.01)])

    def test_round_trip_same_report_is_idempotent_and_has_no_action_authority(self):
        first = store_walk_report(self.job, self.body)
        self.assertEqual(first['state'], 'saved')
        again = store_walk_report(self.job, self.body)
        self.assertEqual(again['state'], 'existing')
        self.assertEqual(first['sha256'], again['sha256'])
        self.assertEqual(first['physicalActions'], 0)
        saved = json.loads((self.job/'walk-reports'/('a'*32+'.json')).read_bytes())
        self.assertEqual(saved, self.body)

    def test_bounded_camera_feedback_summary_is_saved_separately_from_stick_counts(self):
        camera=dict(gainRadiansPerShortSide=-12.,pulses=7,calibrationAttempts=1,terminal=None)
        body=dict(self.body,camera=camera)
        self.assertEqual(store_walk_report(self.job,body)['state'],'saved')
        for key,value in [('pulses',121),('gainRadiansPerShortSide',float('nan')),('terminal','private text')]:
            with self.assertRaisesRegex(ValueError,'camera'):
                store_walk_report(self.job,dict(body,camera={**camera,key:value}))

    def test_conflict_preserves_the_first_report(self):
        store_walk_report(self.job, self.body)
        changed = copy.deepcopy(self.body)
        changed['stopReason'] = 'walk_manual_stop'
        with self.assertRaisesRegex(ValueError, 'conflict'):
            store_walk_report(self.job, changed)
        self.assertEqual(json.loads((self.job/'walk-reports'/('a'*32+'.json')).read_bytes()), self.body)

    def test_planner_and_camera_reasons_remain_separate_with_signed_yaw(self):
        body=copy.deepcopy(self.body);body['observations'][0].update(plannerReason='walk_camera_alignment_required',cameraYawRadians=-.12)
        self.assertEqual(store_walk_report(self.job,body)['state'],'saved')
        body['id']='c'*32;body['observations'][0]['cameraYawRadians']=float('nan')
        with self.assertRaisesRegex(ValueError,'observation'):store_walk_report(self.job,body)

    def test_two_axis_camera_feedback_and_pitch_are_saved_without_changing_legacy_report_schema(self):
        body=copy.deepcopy(self.body)
        body['observations'][0]['cameraPitchRadians']=-.2
        body['camera']=dict(gainRadiansPerShortSide=4,pitchGainRadiansPerShortSide=-3,pulses=2,calibrationAttempts=2,terminal=None,
            feedback=[dict(sequence=4,fraction=.018,turnRadians=-.05,yawBefore=.1,yawAfter=.1,pitchBefore=.3,pitchAfter=.25,axis='y',afterUpMs=180)])
        self.assertEqual(store_walk_report(self.job,body)['state'],'saved')
        body['id']='c'*32;body['camera']['feedback'][0]['pitchAfter']=float('nan')
        with self.assertRaisesRegex(ValueError,'camera_feedback'):store_walk_report(self.job,body)

    def test_camera_feedback_and_real_gesture_duration_are_bounded(self):
        feedback=dict(sequence=10,fraction=-.018,turnRadians=.09,yawBefore=.8,yawAfter=.71,afterUpMs=180)
        camera=dict(gainRadiansPerShortSide=-5.,pulses=2,calibrationAttempts=1,terminal=None,
            minimumFraction=.012,quietResponses=0,feedback=[feedback])
        body=dict(self.body,camera=camera,cameraInput=dict(strokesSubmitted=2,strokesApplied=2,lastDistancePx=19,lastDurationMs=145))
        self.assertEqual(store_walk_report(self.job,body)['state'],'saved')
        for change in ({'feedback':[dict(feedback,turnRadians=float('nan'))]}, {'feedback':[feedback]*33}, {'quietResponses':50}):
            with self.assertRaisesRegex(ValueError,'camera_feedback'):
                store_walk_report(self.job,dict(body,camera={**camera,**change}))
        with self.assertRaisesRegex(ValueError,'camera_input'):
            store_walk_report(self.job,dict(body,cameraInput={**body['cameraInput'],'lastDurationMs':-1}))

    def test_pixels_keys_extra_fields_and_unbounded_rows_are_rejected(self):
        for key, value in [('image', 'data:image/jpeg;base64,x'), ('key', 'secret'), ('id', '../x'), ('executionQualified', True), ('stopFrameAgeMs', float('nan'))]:
            with self.subTest(key=key):
                changed = copy.deepcopy(self.body);changed[key] = value
                with self.assertRaises(ValueError):
                    store_walk_report(self.job, changed)
        changed = copy.deepcopy(self.body);changed['stages'] *= 257
        with self.assertRaisesRegex(ValueError, 'stages'):
            store_walk_report(self.job, changed)
        self.assertFalse((self.job/'walk-reports').exists())

    def test_full_archive_rotates_the_oldest_report_and_accepts_the_new_failure(self):
        folder = self.job/'walk-reports';folder.mkdir()
        for i in range(64):
            (folder/f'{i:032x}.json').write_text('{}')
        self.assertEqual(store_walk_report(self.job,self.body)['state'],'saved')
        self.assertEqual(len(list(folder.iterdir())), 64)
        self.assertTrue((folder/('a'*32+'.json')).exists())
        self.assertFalse((folder/('0'*32+'.json')).exists())

    def test_stage_totals_native_timeline_and_encoder_mode_survive_the_report(self):
        body=copy.deepcopy(self.body);body.update(clientVersion='walk_live_v4',beganAtMs=1793370000000.,observationCount=900,
            stageSummary={'jpeg':dict(count=900,durationMs=1000,maxDurationMs=400,maxAgeMs=410)},
            nativeInputs=[dict(stage='receipt',at_ms=1793370000000.,sequence=4,gesture=1,action=2,pointer_id=0,x=100,y=200,outcome='applied')])
        body['observations'][0].update(stick=[.1,-.2],captureMode='video_frame',captureMs=.1,workerMs=5,encodeMs=4,hashMs=1,
            method='map_anchored_flow',runtimePolicy='pnp-ap3p-continuous-image-support-temporal-v5')
        self.assertEqual(store_walk_report(self.job,body)['state'],'saved')
        body['id']='c'*32;body['nativeInputs'][0]['image']='not_allowed'
        with self.assertRaisesRegex(ValueError,'native_input'):store_walk_report(self.job,body)
