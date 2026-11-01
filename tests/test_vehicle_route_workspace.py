"""The vehicle endpoint is separate and cannot promote a diagnostic observer."""

import hashlib
import json
import unittest
from unittest.mock import patch

from tests import test_route_workspace as fixtures


class VehicleWorkspaceTests(unittest.TestCase):
    def setUp(self):
        import numpy as np

        base = fixtures.RouteWorkspaceTests('test_missing_assets_and_changed_source_never_claim_ready')
        base.setUp()
        self.addCleanup(base.doCleanups)
        self.base = base
        self.workspace, self.job = base.workspace, base.job
        base.attach_fixture_map()
        self.workspace.stop_live(self.job, dict(id='d' * 32))
        manifest = dict(config=dict(profile=dict(mode='vehicle_buttons', steering='stick',
                                                hudProfile='black_russia_scooter_v1')))
        raw = json.dumps(manifest).encode()
        (self.job / 'input/manifest.json').write_bytes(raw)
        receipt_path = self.workspace.current(self.job) / 'receipt.json'
        receipt = json.loads(receipt_path.read_bytes())
        receipt['source_capture_sha256'] = hashlib.sha256(raw).hexdigest()
        receipt_path.write_text(json.dumps(receipt))
        self.reference = type('Reference', (), {'sample': lambda *args: 12.})()
        self.patch_reference = patch('scripts.pilot.route_hud_profile.load_speed_reference', return_value=self.reference)
        self.patch_reference.start()
        self.addCleanup(self.patch_reference.stop)
        self.patch_resource = patch('scripts.pilot.route_workspace.resource_checkpoint')
        self.patch_resource.start()
        self.addCleanup(self.patch_resource.stop)
        self.patch_views = patch('motor_worker.route_reference_view.reference_rotations', return_value=(np.eye(3),) * 8)
        self.patch_views.start()
        self.addCleanup(self.patch_views.stop)
        self.body = dict(id='f' * 32, captureEpoch='e' * 32, width=960, height=540,
            sceneConfirmed=True, vehicleCameraAssumptionConfirmed=True, cameraFollowsBodyConfirmed=True,
            hudProfile='black_russia_scooter_v1', maxSpeedKmh=15, cameraTracking=True,
            cameraControl='continuous_drag_v1', clientVersion='vehicle_live_v1',
            startMode='recognized_route', diagnosticFrames=False)

    def test_explicit_cap_and_attached_camera_contract_echo_without_acquiring_input(self):
        result = self.workspace.start_vehicle(self.job, self.body)
        self.assertEqual(result['mode'], 'vehicle_camera_trace_v1')
        self.assertEqual(result['motionProtocol'], 'applied_vehicle_v1')
        self.assertEqual(result['maxSpeedKmh'], 15)
        self.assertTrue(result['cameraFollowsBodyConfirmed'])
        self.assertEqual(result['physicalActions'], 0)
        first = self.workspace.live['vehicle']
        self.workspace.start_vehicle(self.job, self.body)
        self.assertIs(self.workspace.live['vehicle'], first)
        with self.assertRaisesRegex(ValueError, 'settings_changed'):
            self.workspace.start_vehicle(self.job, dict(self.body, maxSpeedKmh=20))

    def test_missing_or_changed_assumptions_do_not_consume_live_intent(self):
        cases = [{'cameraFollowsBodyConfirmed': False}, {'maxSpeedKmh': True}, {'maxSpeedKmh': 31},
                 {'hudProfile': 'unknown'}, {'cameraTracking': False}, {'clientVersion': 'old'},
                 {'remoteSpeed': 50}]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'explicit_confirmation'):
                self.workspace.start_vehicle(self.job, dict(self.body, **changes))
            self.assertIsNone(self.workspace.live)

    def test_rejected_map_is_not_admitted_by_a_valid_speed_profile(self):
        (self.workspace.current(self.job) / 'state.json').write_text('{"phase":"rejected"}')
        with self.assertRaisesRegex(ValueError, 'route_assets_not_ready'):
            self.workspace.start_vehicle(self.job, self.body)
        self.assertIsNone(self.workspace.live)

    def test_observer_cannot_be_promoted_to_vehicle_and_foot_cannot_replace_it(self):
        request = {key: self.body[key] for key in ('id', 'captureEpoch', 'width', 'height', 'sceneConfirmed')}
        self.workspace.start_live(self.job, request)
        with self.assertRaisesRegex(ValueError, 'cannot_be_promoted'):
            self.workspace.start_vehicle(self.job, self.body)
        self.workspace.stop_live(self.job, dict(id=self.body['id']))
        self.body['id'] = '9' * 32
        self.workspace.start_vehicle(self.job, self.body)
        walk = dict(request, id='9' * 32, footCameraAssumptionConfirmed=True, clientVersion='walk_live_v8')
        with self.assertRaisesRegex(ValueError, 'cannot_be_promoted'):
            self.workspace.start_walk(self.job, walk)

    def test_unknown_speed_or_unknown_jpeg_is_neutral_and_motion_feedback_is_required(self):
        import cv2 as cv
        import numpy as np

        self.workspace.start_vehicle(self.job, self.body)
        _, encoded = cv.imencode('.jpg', np.zeros((540, 960, 3), np.uint8))
        frame = dict(id=self.body['id'], captureEpoch=self.body['captureEpoch'], sequence=1)
        with self.assertRaisesRegex(ValueError, 'motion_feedback_required'):
            self.workspace.observe_jpeg(self.job, frame, encoded.tobytes())
        self.assertEqual(self.workspace.live['sequence'], 0)
        def reader(image, **kwargs):
            self.assertEqual(image.shape, (540, 960, 3))
            self.assertEqual(kwargs['jpeg_sha256'], hashlib.sha256(encoded).hexdigest())
            return dict(kwargs, status='unknown', speed_kmh=None, confidence=0.)
        with patch('scripts.pilot.route_hud_profile.read_live_speed', side_effect=reader):
            result = self.workspace.observe_jpeg(self.job, dict(frame, motionActive=False), encoded.tobytes())
        self.assertEqual(result['vehicle']['pedal'], 'coast')
        self.assertEqual(result['vehicle']['steering'], 0.)
        self.assertEqual(result['physicalActions'], 0)
        self.assertNotIn('walk', result)
        self.assertEqual(result['speedObservation']['source_rgb_sha256'], result['pose']['source_rgb_sha256'])

    def test_no_source_speed_profile_does_not_create_vehicle_session(self):
        with patch('scripts.pilot.route_hud_profile.load_speed_reference', return_value=None):
            with self.assertRaisesRegex(ValueError, 'source_speed_not_prepared'):
                self.workspace.start_vehicle(self.job, self.body)
        self.assertIsNone(self.workspace.live)

    def test_explicit_longer_budget_is_echoed_and_cannot_change_in_place(self):
        body = dict(self.body, maxSeconds=1200)
        result = self.workspace.start_vehicle(self.job, body)
        self.assertEqual(result['maxSeconds'], 1200)
        self.assertEqual(self.workspace.live['observation_limit'], 36000)
        with self.assertRaisesRegex(ValueError, 'settings_changed'):
            self.workspace.start_vehicle(self.job, dict(body, maxSeconds=1800))
