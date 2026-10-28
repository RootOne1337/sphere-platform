"""Read-only workspace protocol, exact image binding and uncertain-start fences."""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot.route_workspace import RouteWorkspaces, route_resource_profile, resource_checkpoint


class RouteWorkspaceTests(unittest.TestCase):
    def test_short_cpu_export_and_live_budget_do_not_require_twelve_gib(self):
        (self.job/'input/video.h264').write_bytes(b'x'*1024)
        profile=route_resource_profile(self.job)
        self.assertGreaterEqual(profile['minRamGiB'],6)
        self.assertLess(profile['minRamGiB'],12)
        self.assertEqual(route_resource_profile(self.job,'live')['minRamGiB'],6)
        from scripts.pilot.resource_guard import evaluate
        snapshot=dict(system='Windows',freeDiskBytes=30*2**30,availableRamBytes=11*2**30,totalRamBytes=48*2**30,
            committedBytes=65*2**30,commitLimitBytes=96*2**30,volumeHealthStatus='Healthy',volumeOperationalStatus=['OK'])
        with patch('scripts.pilot.route_workspace.collect',return_value=snapshot):
            resource_checkpoint(self.job,profile=profile)
            with self.assertRaisesRegex(RuntimeError,'resource_guard'):
                resource_checkpoint(self.job)  # Other experiments keep the old guard.
        self.assertEqual(evaluate(snapshot,min_ram_gib=profile['minRamGiB']),[])
        snapshot['committedBytes']=90*2**30
        self.assertIn('commit_headroom_low',evaluate(snapshot,min_ram_gib=profile['minRamGiB']))

    def test_unknown_or_large_capture_keeps_a_conservative_budget(self):
        self.assertEqual(route_resource_profile(self.job)['minRamGiB'],12)
        with patch.object(Path,'stat',return_value=type('Stat',(),{'st_size':2**31,'st_mode':0o100644})()):
            self.assertGreaterEqual(route_resource_profile(self.job)['minRamGiB'],12)

    def test_recording_endpoint_coverage_detects_missing_start_and_end(self):
        from scripts.pilot.prepare_route_workspace import source_endpoint_coverage

        frames = [{'relative_ticks_90k': 0}, {'relative_ticks_90k': 30 * 90000}]
        self.assertTrue(source_endpoint_coverage(frames, .5, 29.5)['endpoints_observed'])
        self.assertFalse(source_endpoint_coverage(frames, 0., 25.)['endpoints_observed'])
        self.assertFalse(source_endpoint_coverage(frames, 2., 30.)['endpoints_observed'])
        with self.assertRaisesRegex(ValueError, 'frames_missing'):
            source_endpoint_coverage([], 0., 1.)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.job = self.root/('a'*32)
        (self.job/'input').mkdir(parents=True)
        (self.job/'geometry.json').write_text('{}')
        (self.job/'input/manifest.json').write_text('{}')
        self.now = 10.
        self.workspace = RouteWorkspaces(self.root, Path('unused-python.exe'), clock=lambda:self.now)
        self.identity = 'c'*32

    def test_missing_assets_and_changed_source_never_claim_ready(self):
        self.assertEqual(self.workspace.status(self.job)['phase'], 'not_prepared')
        folder = self.job/'navigation'/self.identity
        folder.mkdir(parents=True)
        (folder.parent/'active.json').write_text(json.dumps(dict(id=self.identity)))
        (folder/'state.json').write_text('{"phase":"ready"}')
        (folder/'receipt.json').write_text(json.dumps(dict(geometry_sha256='0'*64,source_capture_sha256='0'*64)))
        self.assertEqual(self.workspace.status(self.job)['phase'], 'rejected')

    def test_old_ready_receipt_without_coverage_evidence_is_rejected(self):
        folder = self.job/'navigation'/self.identity
        folder.mkdir(parents=True)
        (folder.parent/'active.json').write_text(json.dumps(dict(id=self.identity)))
        (folder/'state.json').write_text('{"phase":"ready"}')
        source = hashlib.sha256(b'{}').hexdigest()
        (folder/'receipt.json').write_text(json.dumps(dict(geometry_sha256=source, source_capture_sha256=source,
            map_support=dict(all_reference_neighborhoods_supported=True))))
        result = self.workspace.status(self.job)
        self.assertEqual(result['phase'], 'rejected')
        self.assertEqual(result['error'], 'route_map_has_unobserved_sections')

    def test_ready_without_receipt_cannot_open_a_live_session(self):
        folder = self.job/'navigation'/self.identity
        folder.mkdir(parents=True)
        (folder.parent/'active.json').write_text(json.dumps(dict(id=self.identity)))
        (folder/'state.json').write_text('{"phase":"ready"}')
        result=self.workspace.status(self.job)
        self.assertEqual(result['phase'],'rejected')
        self.assertEqual(result['error'],'route_receipt_missing')

    def test_legacy_receipt_without_source_coverage_can_be_rebuilt_without_a_server_error(self):
        self.attach_fixture_map()
        self.workspace.stop_live(self.job,dict(id='d'*32))
        folder=self.workspace.current(self.job)
        receipt=json.loads((folder/'receipt.json').read_text())
        receipt.pop('source_coverage')
        (folder/'receipt.json').write_text(json.dumps(receipt))
        with patch('scripts.pilot.route_workspace.resource_checkpoint',side_effect=RuntimeError('resource_guard')):
            with self.assertRaisesRegex(RuntimeError,'resource_guard'):
                self.workspace.prepare(self.job,dict(id='f'*32))

    def test_rejected_coverage_keeps_actual_time_ranges_for_the_ui(self):
        self.attach_fixture_map()
        self.workspace.stop_live(self.job,dict(id='d'*32))
        folder=self.workspace.current(self.job)
        receipt=json.loads((folder/'receipt.json').read_text())
        receipt.update(first_seconds=0.,last_seconds=28.258,
            source_coverage=dict(recording_start_seconds=0.,recording_end_seconds=33.258,
                uncovered_start_seconds=0.,uncovered_end_seconds=5.,endpoints_observed=False))
        receipt['map_support']['all_reference_intervals_observed']=False
        receipt['map_support']['unobserved_intervals']=[dict(start_seconds=10.807,end_seconds=12.341)]
        (folder/'receipt.json').write_text(json.dumps(receipt))
        result=self.workspace.status(self.job)
        self.assertEqual(result['phase'],'rejected')
        self.assertEqual(result['summary']['last_seconds'],28.258)
        self.assertEqual(result['summary']['source_coverage']['uncovered_end_seconds'],5.)
        with patch('scripts.pilot.route_workspace.subprocess.Popen') as process, \
             patch('scripts.pilot.route_workspace.resource_checkpoint') as guard:
            with self.assertRaisesRegex(ValueError,'route_camera_recovery_required'):
                self.workspace.prepare(self.job,dict(id='f'*32))
        process.assert_not_called()
        guard.assert_not_called()
        self.assertFalse((self.job/'navigation'/('f'*32)).exists())

    def test_resource_refusal_does_not_consume_an_intent_or_replace_the_active_map(self):
        with patch('scripts.pilot.route_workspace.resource_checkpoint',side_effect=RuntimeError('resource_guard')), \
             patch('scripts.pilot.route_workspace.subprocess.Popen') as process:
            with self.assertRaisesRegex(RuntimeError,'resource_guard'):
                self.workspace.prepare(self.job,dict(id=self.identity))
        process.assert_not_called()
        self.assertFalse((self.job/'navigation/active.json').exists())
        self.assertFalse((self.job/'navigation'/self.identity).exists())

    def test_existing_preparation_is_read_back_without_a_process_or_resource_recheck(self):
        folder = self.job/'navigation'/self.identity
        folder.mkdir(parents=True)
        (folder/'state.json').write_text('{"phase":"preparing"}')
        with patch('scripts.pilot.route_workspace.subprocess.Popen') as process, \
             patch('scripts.pilot.route_workspace.resource_checkpoint') as guard:
            result = self.workspace.prepare(self.job,dict(id=self.identity))
        self.assertEqual(result['phase'],'preparing')
        process.assert_not_called()
        guard.assert_not_called()

    def test_stop_before_start_retires_the_intent_so_late_start_cannot_resurrect_it(self):
        self.assertEqual(self.workspace.stop_live(self.job,dict(id=self.identity))['phase'],'closed')
        with self.assertRaisesRegex(ValueError,'retired'):
            self.workspace.start_live(self.job,dict(id=self.identity,captureEpoch='e'*32,width=1920,height=1080,sceneConfirmed=True))

    def test_retired_intents_are_bounded_and_eventually_expire(self):
        self.workspace.stop_live(self.job,dict(id=self.identity))
        self.now += 599
        self.workspace._expire()
        self.assertIn(self.identity, self.workspace.retired)
        self.now += 2
        self.workspace._expire()
        self.assertNotIn(self.identity, self.workspace.retired)

    def test_scene_confirmation_and_unknown_body_fields_do_not_consume_an_intent(self):
        for extra in ({'sceneConfirmed':False},{'remoteUrl':'https://example.com'}):
            body=dict(id=self.identity,captureEpoch='e'*32,width=1920,height=1080,sceneConfirmed=True)
            body.update(extra)
            with self.assertRaisesRegex(ValueError,'confirmation_or_binding'):
                self.workspace.start_live(self.job,body)
        self.assertIsNone(self.workspace.live)

    def attach_fixture_map(self):
        from tests.test_motor_route_localization import SparseLocalizationTests
        fixture = SparseLocalizationTests('test_blank_real_rgb_has_no_pose')
        fixture.setUp()
        folder = self.job/'navigation'/self.identity
        folder.mkdir(parents=True)
        (folder.parent/'active.json').write_text(json.dumps(dict(id=self.identity)))
        (folder/'state.json').write_text('{"phase":"ready"}')
        sha = fixture.route.save(folder/'route.json')
        source = hashlib.sha256(b'{}').hexdigest()
        receipt=dict(sha256=sha,geometry_sha256=source,source_capture_sha256=source,cameras=8,landmarks=240,
            pipeline_sha256=fixture.route.pipeline_sha256,
            camera_trace_only=True,map_support=dict(all_reference_neighborhoods_supported=True,
                                                   all_reference_intervals_observed=True),
            source_coverage=dict(endpoints_observed=True))
        (folder/'receipt.json').write_text(json.dumps(receipt))
        with patch('scripts.pilot.route_workspace.resource_checkpoint'):
            self.workspace.start_live(self.job,dict(id='d'*32,captureEpoch='e'*32,width=960,height=540,sceneConfirmed=True))

    def test_real_jpeg_has_no_archive_or_input_and_replayed_sequence_is_refused(self):
        import cv2 as cv
        import numpy as np

        self.attach_fixture_map()
        ok, encoded = cv.imencode('.jpg',np.zeros((540,960,3),np.uint8))
        self.assertTrue(ok)
        body=dict(id='d'*32,captureEpoch='e'*32,sequence=1,jpeg=base64.b64encode(encoded).decode())
        files=set(p.relative_to(self.job) for p in self.job.rglob('*') if p.is_file())
        result=self.workspace.observe(self.job,body)
        self.assertEqual(result['jpegSha256'],hashlib.sha256(encoded).hexdigest())
        self.assertEqual(result['pose']['state'],'unknown')
        self.assertEqual(result['framesArchived'],0)
        self.assertEqual(result['verificationPolicy'],'pnp-image-coverage-v1')
        self.assertEqual(result['physicalActions'],0)
        self.assertFalse(result['executionQualified'])
        self.assertEqual(files,set(p.relative_to(self.job) for p in self.job.rglob('*') if p.is_file()))
        with self.assertRaisesRegex(ValueError,'not_bound'):
            self.workspace.observe(self.job,body)
        self.now += 121
        self.assertEqual(self.workspace.live_status()['phase'],'idle')

    def test_walk_requires_separate_confirmation_and_cannot_promote_observer(self):
        self.attach_fixture_map()
        body=dict(id='d'*32,captureEpoch='e'*32,width=960,height=540,sceneConfirmed=True)
        with self.assertRaisesRegex(ValueError,'explicit_confirmation'):
            self.workspace.start_walk(self.job,body)
        with self.assertRaisesRegex(ValueError,'cannot_be_promoted'):
            self.workspace.start_walk(self.job,dict(body,footCameraAssumptionConfirmed=True))
        self.assertNotIn('walk',self.workspace.live)

    def test_walk_plan_is_separate_finite_and_unknown_jpeg_stays_neutral(self):
        import cv2 as cv
        import numpy as np

        self.attach_fixture_map()
        self.workspace.stop_live(self.job,dict(id='d'*32))
        body=dict(id='f'*32,captureEpoch='e'*32,width=960,height=540,sceneConfirmed=True,footCameraAssumptionConfirmed=True)
        with patch('scripts.pilot.route_workspace.resource_checkpoint'):
            result=self.workspace.start_walk(self.job,body)
        self.assertEqual(result['mode'],'foot_camera_trace_v1')
        self.assertEqual(result['secondsRemaining'],60)
        self.assertEqual(self.workspace.live['tracker'].mask[400,480],0)
        first=self.workspace.live['walk']
        with patch('scripts.pilot.route_workspace.resource_checkpoint'):
            self.workspace.start_walk(self.job,body)
        self.assertIs(self.workspace.live['walk'],first)
        _,encoded=cv.imencode('.jpg',np.zeros((540,960,3),np.uint8))
        value=self.workspace.observe(self.job,dict(id='f'*32,captureEpoch='e'*32,sequence=1,jpeg=base64.b64encode(encoded).decode()))
        self.assertEqual(value['walk']['stick'],[0.,0.])
        self.assertEqual(value['walk']['phase'],'waiting')
        self.assertEqual(value['physicalActions'],0)

    def test_incompatible_extractor_is_rejected_before_a_live_session_can_open(self):
        self.attach_fixture_map()
        self.workspace.stop_live(self.job,dict(id='d'*32))
        folder=self.workspace.current(self.job)
        receipt=json.loads((folder/'receipt.json').read_text())
        receipt['pipeline_sha256']='0'*64
        (folder/'receipt.json').write_text(json.dumps(receipt))
        self.assertEqual(self.workspace.status(self.job)['error'],'route_feature_runtime_mismatch')
        with self.assertRaisesRegex(ValueError,'not_ready'):
            self.workspace.start_walk(self.job,dict(id='f'*32,captureEpoch='e'*32,width=960,height=540,
                sceneConfirmed=True,footCameraAssumptionConfirmed=True))

    def test_jpeg_dimensions_are_checked_before_decode_and_failed_confirmation_cannot_open_input(self):
        import cv2 as cv
        import numpy as np

        self.attach_fixture_map()
        _,encoded=cv.imencode('.jpg',np.zeros((200,200,3),np.uint8))
        body=dict(id='d'*32,captureEpoch='e'*32,sequence=1,jpeg=base64.b64encode(encoded).decode())
        with patch('cv2.imdecode') as decode:
            with self.assertRaisesRegex(ValueError,'jpeg_geometry'):
                self.workspace.observe(self.job,body)
            decode.assert_not_called()
