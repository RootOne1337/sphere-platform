"""Read-only workspace protocol, exact image binding and uncertain-start fences."""
import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot.route_workspace import RouteWorkspaces


class RouteWorkspaceTests(unittest.TestCase):
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
            camera_trace_only=True,map_support=dict(all_reference_neighborhoods_supported=True))
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
        self.assertEqual(result['physicalActions'],0)
        self.assertFalse(result['executionQualified'])
        self.assertEqual(files,set(p.relative_to(self.job) for p in self.job.rglob('*') if p.is_file()))
        with self.assertRaisesRegex(ValueError,'not_bound'):
            self.workspace.observe(self.job,body)
        self.now += 121
        self.assertEqual(self.workspace.live_status()['phase'],'idle')

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
