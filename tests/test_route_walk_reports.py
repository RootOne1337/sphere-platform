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

    def test_sixty_four_reports_preserve_history_and_then_refuse_new_files(self):
        folder = self.job/'walk-reports';folder.mkdir()
        for i in range(64):
            (folder/f'{i:032x}.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'retention_quota'):
            store_walk_report(self.job, self.body)
        self.assertEqual(len(list(folder.iterdir())), 64)
