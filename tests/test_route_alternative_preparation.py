"""Selected native alternatives are independent of failed legacy primaries."""
import hashlib
import json
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.pilot.route_preparation_source import (
    MODEL_FILES,
    attempt_cancelled,
    attempt_source,
    cancel_marker,
    preparation_sources,
    resolve_alternative_source,
)
from scripts.pilot.route_workspace import RouteWorkspaces


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


class AlternativePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.job = self.root/('a'*32)
        write(self.job/'input/manifest.json', {'capture': 'original'})
        write(self.job/'prepared/reconstruction-input.json', {'images': []})
        write(self.job/'geometry.json', {'old_primary': 'incomplete'})
        write(self.job/'state.json', {'phase': 'failed', 'error': 'resource_guard'})
        self.identity = 'historical-verified'
        self.alt = self.job/'alternatives'/self.identity
        geometry = dict(schema='sphere-recovered-scene-v1', source_manifest_sha256=sha(self.job/'input/manifest.json'),
                        execution_qualified=False, cameras=[{'image': 'a.png'}, {'image': 'b.png'}],
                        points=[[1, 2, 3]]*300)
        write(self.alt/'geometry.json', geometry)
        write(self.alt/'receipt.json', dict(schema='sphere-alternative-geometry-v1', id=self.identity,
            scope='DIAGNOSTIC_ONLY', execution_qualified=False,
            source_manifest_sha256=geometry['source_manifest_sha256'], geometry_sha256=sha(self.alt/'geometry.json')))
        native = self.alt/'native'
        (native/'model').mkdir(parents=True)
        for name in MODEL_FILES:
            (native/'model'/name).write_bytes(('native-measurements-'+name).encode())
        write(native/'assessment.json', dict(route_admissible=True, scene_admissible=True, registered=2, points=300,
            source_coverage=dict(endpoints_observed=True, all_intervals_observed=True)))
        write(native/'producer-proof.json', {'historical_producer': 'verified-copy'})
        write(native/'source.json', dict(schema='sphere-alternative-native-source-v1', alternative_id=self.identity,
            scope='READ_ONLY_ROUTE_ASSETS', execution_qualified=False, geometry_sha256=sha(self.alt/'geometry.json'),
            source_manifest_sha256=sha(self.job/'input/manifest.json'),
            reconstruction_input_sha256=sha(self.job/'prepared/reconstruction-input.json'),
            model_sha256={name: sha(native/'model'/name) for name in MODEL_FILES},
            evidence_sha256={name: sha(native/name) for name in ('assessment.json', 'producer-proof.json')}))
        self.workspace = RouteWorkspaces(self.root, Path('unused.exe'))
        self.attempt = 'c'*32

    def attach_attempt(self, phase='awaiting_qualification'):
        selected = resolve_alternative_source(self.job, self.identity)
        folder = self.job/'navigation'/self.attempt
        write(folder/'intent.json', dict(id=self.attempt, alternativeId=self.identity, sourceBinding=selected['binding'],
                                        cancellationPolicy=dict(parentCancelAtIntent=cancel_marker(self.job/'CANCEL'))))
        write(folder.parent/'active.json', dict(id=self.attempt))
        write(folder/'state.json', dict(phase=phase))
        write(folder/'receipt.json', dict(geometry_sha256=selected['binding']['geometry_sha256'],
            sha256='b'*64,
            source_capture_sha256=selected['binding']['source_manifest_sha256'], source_binding=selected['binding'],
            pipeline_sha256='b'*64, cameras=2, landmarks=300,
            map_support=dict(all_reference_neighborhoods_supported=True, all_reference_intervals_observed=True),
            source_coverage=dict(endpoints_observed=True)))
        return folder

    def test_only_exact_admitted_native_source_is_preparable(self):
        sources = preparation_sources(self.job)
        self.assertEqual([item['alternativeId'] for item in sources], [self.identity])
        self.assertEqual(sources[0]['runtime_family'], 'reference_lk')
        (self.alt/'native/model/images.bin').write_bytes(b'different native observations')
        self.assertEqual(preparation_sources(self.job), [])
        with self.assertRaisesRegex(ValueError, 'native_changed'):
            resolve_alternative_source(self.job, self.identity)

    def test_v2_uses_alternative_index_and_rejects_changed_frame_or_original_index(self):
        native = self.alt/'native'
        manifest = self.job/'input/manifest.json'
        manifest_copy = native/'input/manifest.json'
        manifest_copy.parent.mkdir(parents=True)
        manifest_copy.write_bytes(manifest.read_bytes())
        frames, rows, hashes = [], [], {}
        for i in range(2):
            frame = dict(relative_ticks_90k=i*9000, worker_observed_at_ms=float(i), sha256=str(i)*64)
            frames.append(frame)
            name = f'{i:08d}.png'
            path = native/'prepared/images'/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes([i+1]))
            hashes[name] = sha(path)
            rows.append(dict(image='images/'+name, source_index=i, relative_ticks_90k=frame['relative_ticks_90k'],
                worker_observed_at_ms=frame['worker_observed_at_ms'], source_access_unit_sha256=frame['sha256'],
                png_sha256=hashes[name], bytes=1))
        index = native/'prepared/reconstruction-input.json'
        write(index, dict(schema='sphere-reconstruction-input-v1', clip='clip', geometry=[1920, 1080],
                          source_manifest_sha256=sha(manifest), images=rows))
        source = native/'source.json'
        record = json.loads(source.read_bytes())
        record.update(schema='sphere-alternative-native-source-v2',
                      original_reconstruction_input_sha256=record['reconstruction_input_sha256'],
                      reconstruction_input_sha256=sha(index), images_sha256=hashes)
        write(source, record)
        capture = types.SimpleNamespace(manifest={'id': 'clip'}, geometry=(1920, 1080), frames=frames)
        with patch('motor_worker.browser_teach.validate_browser', return_value=capture):
            selected = resolve_alternative_source(self.job, self.identity)
            self.assertEqual(selected['index_path'], index)
            self.assertEqual(selected['binding']['schema'], 'sphere-route-preparation-source-v2')
            (native/'prepared/images/00000000.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'native_index'):
                resolve_alternative_source(self.job, self.identity)
            (native/'prepared/images/00000000.png').write_bytes(b'\x01')
            write(self.job/'prepared/reconstruction-input.json', {'changed': True})
            with self.assertRaisesRegex(ValueError, 'native_binding'):
                resolve_alternative_source(self.job, self.identity)

    def test_native_source_cannot_rebind_to_changed_index_or_execution_claim(self):
        source = self.alt/'native/source.json'
        record = json.loads(source.read_bytes())
        record['execution_qualified'] = True
        write(source, record)
        with self.assertRaisesRegex(ValueError, 'native_binding'):
            resolve_alternative_source(self.job, self.identity)
        record['execution_qualified'] = False
        write(source, record)
        write(self.job/'prepared/reconstruction-input.json', {'changed': True})
        with self.assertRaisesRegex(ValueError, 'native_binding'):
            resolve_alternative_source(self.job, self.identity)

    def test_attempt_keeps_selected_source_when_primary_or_review_pointer_changes(self):
        folder = self.attach_attempt()
        before = attempt_source(self.job, folder)
        write(self.job/'geometry.json', {'totally_different_primary': True})
        write(self.job/'alternative-selection.json', {'id': 'different-display-only'})
        self.assertEqual(attempt_source(self.job, folder), before)
        record = json.loads((folder/'intent.json').read_bytes())
        record['sourceBinding']['geometry_sha256'] = '0'*64
        write(folder/'intent.json', record)
        with self.assertRaisesRegex(ValueError, 'source_changed'):
            attempt_source(self.job, folder)

    def test_repeated_intent_with_different_source_is_not_reused(self):
        self.attach_attempt()
        with self.assertRaisesRegex(ValueError, 'intent_source_changed'):
            self.workspace.prepare(self.job, dict(id=self.attempt))
        with patch('scripts.pilot.route_workspace.resource_checkpoint') as guard:
            result = self.workspace.prepare(self.job, dict(id=self.attempt, alternativeId=self.identity))
        self.assertEqual(result['phase'], 'awaiting_qualification')
        guard.assert_not_called()

    def test_alternative_uses_fresh_intent_despite_three_old_primary_failures(self):
        for digit in ('1', '2', '3'):
            folder = self.job/'navigation'/(digit*32)
            write(folder/'intent.json', dict(id=digit*32))
            write(folder/'state.json', dict(phase='failed', error='resource_guard'))
        process = types.SimpleNamespace()
        with patch('scripts.pilot.route_workspace.resource_checkpoint'), \
             patch('scripts.pilot.route_workspace.spawn_owned', return_value=process) as spawn, \
             patch('scripts.pilot.route_workspace.threading.Thread'):
            result = self.workspace.prepare(self.job, dict(id=self.attempt, alternativeId=self.identity))
        self.assertEqual(result['phase'], 'preparing')
        self.assertEqual(result['source']['alternativeId'], self.identity)
        self.assertEqual(spawn.call_count, 1)
        self.assertTrue((self.job/'navigation'/self.attempt/'intent.json').is_file())
        self.assertEqual(json.loads((self.job/'state.json').read_bytes())['error'], 'resource_guard')

    def test_no_display_geometry_without_native_bundle_can_start_preparation(self):
        (self.alt/'native/source.json').unlink()
        with patch('scripts.pilot.route_workspace.resource_checkpoint'), \
             patch('scripts.pilot.route_workspace.spawn_owned') as spawn:
            with self.assertRaises((OSError, ValueError)):
                self.workspace.prepare(self.job, dict(id=self.attempt, alternativeId=self.identity))
        spawn.assert_not_called()
        self.assertFalse((self.job/'navigation'/self.attempt).exists())

    def test_qualification_is_required_and_changed_native_source_revokes_ready(self):
        self.attach_attempt()
        module = types.ModuleType('scripts.pilot.route_reference_lk_export')
        module.validate_reference_lk_receipt = lambda *args, **kwargs: None
        def unqualified(*args, **kwargs):
            raise ValueError('missing_reviewed_qualification')
        module.validate_reference_lk_qualification = unqualified
        with patch.dict('sys.modules', {'scripts.pilot.route_reference_lk_export': module}):
            status = self.workspace.status(self.job)
            self.assertEqual(status['phase'], 'awaiting_qualification')
            self.assertEqual(status['error'], 'route_reference_lk_unqualified')
            self.assertFalse(self.workspace.preparing(self.job))
            module.validate_reference_lk_qualification = lambda *args, **kwargs: None
            ready = self.workspace.status(self.job)
            self.assertEqual(ready['phase'], 'ready')
            self.assertTrue(ready['controlledExperimentalTestOnly'])
            self.assertFalse(ready['executionQualified'])
            (self.alt/'native/model/points3D.bin').write_bytes(b'changed')
            self.assertEqual(self.workspace.status(self.job)['phase'], 'rejected')

    def test_unknown_source_selector_keys_are_rejected_before_resources(self):
        with patch('scripts.pilot.route_workspace.resource_checkpoint') as guard:
            with self.assertRaisesRegex(ValueError, 'preparation_intent'):
                self.workspace.prepare(self.job, dict(id=self.attempt, alternativeId=self.identity, path='outside'))
        guard.assert_not_called()

    def test_old_parent_cancel_is_preserved_but_new_touch_or_attempt_cancel_stops(self):
        parent = self.job/'CANCEL'
        parent.write_bytes(b'old reconstruction cancellation')
        folder = self.attach_attempt()
        record = json.loads((folder/'intent.json').read_bytes())
        record['cancellationPolicy'] = dict(parentCancelAtIntent=cancel_marker(parent))
        write(folder/'intent.json', record)
        original = parent.read_bytes()
        self.assertFalse(attempt_cancelled(self.job, folder))
        process = types.SimpleNamespace(poll=lambda: 0)
        self.workspace._monitor_owned_process(folder, process, None, None)
        self.assertEqual(json.loads((folder/'state.json').read_bytes())['phase'], 'awaiting_qualification')
        stat = parent.stat()
        os.utime(parent, ns=(stat.st_atime_ns, stat.st_mtime_ns+1_000_000))
        self.assertTrue(attempt_cancelled(self.job, folder))
        self.assertEqual(parent.read_bytes(), original)
        record['cancellationPolicy'] = dict(parentCancelAtIntent=cancel_marker(parent))
        write(folder/'intent.json', record)
        (folder/'CANCEL').touch()
        self.assertTrue(attempt_cancelled(self.job, folder))

    def test_new_alternative_does_not_consume_old_parent_cancel_as_new_input(self):
        parent = self.job/'CANCEL'
        parent.write_bytes(b'preserve historical bytes')
        with patch('scripts.pilot.route_workspace.resource_checkpoint') as guard, \
             patch('scripts.pilot.route_workspace.spawn_owned', return_value=types.SimpleNamespace()), \
             patch('scripts.pilot.route_workspace.threading.Thread'):
            self.workspace.prepare(self.job, dict(id=self.attempt, alternativeId=self.identity))
        self.assertEqual(guard.call_args.args[0], self.job/'navigation'/self.attempt)
        self.assertEqual(parent.read_bytes(), b'preserve historical bytes')
        self.assertFalse(attempt_cancelled(self.job, self.job/'navigation'/self.attempt))
        # Primary preparations keep their historical parent-cancel semantics.
        legacy = self.job/'navigation'/('f'*32)
        write(legacy/'intent.json', dict(id='f'*32))
        self.assertTrue(attempt_cancelled(self.job, legacy))

    def test_worker_exports_selected_native_bundle_without_primary_sfm_or_model_rebuild(self):
        from scripts.pilot.prepare_route_workspace import prepare
        folder = self.attach_attempt(phase='preparing')
        module = types.ModuleType('scripts.pilot.route_reference_lk_export')
        calls = []
        def export(*args, **kwargs):
            calls.append((args, kwargs))
            return dict(first_seconds=0., last_seconds=1.,
                        map_support=dict(all_reference_neighborhoods_supported=True,
                                         all_reference_intervals_observed=True))
        module.export = export
        manifest_bytes = (self.job/'input/manifest.json').read_bytes()
        capture = types.SimpleNamespace(geometry=(1920, 1080), manifest=json.loads(manifest_bytes),
            originals={'manifest.json': manifest_bytes},
            frames=[dict(relative_ticks_90k=0), dict(relative_ticks_90k=90000)])
        with patch.dict('sys.modules', {'scripts.pilot.route_reference_lk_export': module}), \
             patch('motor_worker.browser_teach.validate_browser', return_value=capture), \
             patch('scripts.pilot.route_motion_audit.audit', return_value=dict(rapid_reversals=[], speed_outliers=[])), \
             patch('scripts.pilot.prepare_route_workspace.resource_checkpoint'), \
             patch('scripts.pilot.prepare_route_workspace.route_source_model') as primary, \
             patch('scripts.pilot.route_masks.capture_exclusions', return_value=()), \
             patch('scripts.pilot.prepare_route_workspace.TaskResourceMonitor'):
            prepare(self.job, self.attempt)
        primary.assert_not_called()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0][0], self.alt/'native/model')
        self.assertEqual(calls[0][1]['source_geometry_path'], self.alt/'geometry.json')
        receipt = json.loads((folder/'receipt.json').read_bytes())
        self.assertEqual(receipt['source_binding']['alternative_id'], self.identity)
        self.assertEqual(json.loads((folder/'state.json').read_bytes())['phase'], 'awaiting_qualification')

    def test_worker_refuses_control_change_during_export(self):
        from scripts.pilot.prepare_route_workspace import prepare

        folder = self.attach_attempt(phase='preparing')
        (folder/'receipt.json').unlink()
        write(self.job/'control.json', {'mask': 'game'})
        manifest_bytes = (self.job/'input/manifest.json').read_bytes()
        capture = types.SimpleNamespace(geometry=(1920, 1080), manifest=json.loads(manifest_bytes),
            originals={'manifest.json': manifest_bytes},
            frames=[dict(relative_ticks_90k=0), dict(relative_ticks_90k=90000)])
        module = types.ModuleType('scripts.pilot.route_reference_lk_export')

        def export(*args, **kwargs):
            write(self.job/'control.json', {'mask': 'none'})
            return dict(first_seconds=0., last_seconds=1.,
                        map_support=dict(all_reference_neighborhoods_supported=True,
                                         all_reference_intervals_observed=True))

        module.export = export
        with patch.dict('sys.modules', {'scripts.pilot.route_reference_lk_export': module}), \
             patch('motor_worker.browser_teach.validate_browser', return_value=capture), \
             patch('scripts.pilot.route_motion_audit.audit', return_value=dict(rapid_reversals=[], speed_outliers=[])), \
             patch('scripts.pilot.prepare_route_workspace.resource_checkpoint'), \
             patch('scripts.pilot.prepare_route_workspace.TaskResourceMonitor'):
            with self.assertRaisesRegex(ValueError, 'route_mask_plan_source_binding'):
                prepare(self.job, self.attempt)
        self.assertFalse((folder/'receipt.json').exists())

    def test_live_immutable_source_fence_closes_caches_when_source_is_touched(self):
        path = self.alt/'native/model/images.bin'
        closed = []
        route = types.SimpleNamespace(close=lambda: closed.append('route'))
        tracker = types.SimpleNamespace(route=route, close=lambda: closed.append('tracker'))
        session = dict(id='e'*32, tracker=tracker, source_paths=(path,),
                       source_stamp=self.workspace._runtime_source_stamp((path,)))
        self.workspace.live = session
        self.workspace._validate_live_source(session)
        self.assertEqual(closed, [])
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns+1_000_000))
        with self.assertRaisesRegex(ValueError, 'route_source_changed'):
            self.workspace._validate_live_source(session)
        self.assertEqual(closed, ['tracker', 'route'])
        self.assertIsNone(self.workspace.live)

    def test_alternate_start_requires_exact_expected_source_before_loading(self):
        self.attach_attempt()
        selected = resolve_alternative_source(self.job, self.identity)
        from scripts.pilot.route_preparation_source import public_source
        source = public_source(selected)
        body = dict(id='e'*32, captureEpoch='f'*32, width=1920, height=1080, sceneConfirmed=True)
        with patch('scripts.pilot.route_workspace.resource_checkpoint') as guard, \
             patch('motor_worker.route_reference_lk.ReferenceLKRoute.load') as load:
            with self.assertRaisesRegex(ValueError, 'source_confirmation_required'):
                self.workspace.start_live(self.job, body)
            with self.assertRaisesRegex(ValueError, 'start_source_changed'):
                self.workspace.start_live(self.job, dict(body, expectedSource=dict(source, geometry_sha256='0'*64)))
        guard.assert_not_called()
        load.assert_not_called()

    def test_thrown_source_reresolution_after_tracker_creation_releases_both_leases(self):
        self.attach_attempt()
        from scripts.pilot.route_preparation_source import public_source
        selected = resolve_alternative_source(self.job, self.identity)
        route = types.SimpleNamespace(profile=types.SimpleNamespace(width=960, height=540), close=Mock())
        tracker = types.SimpleNamespace(route=route, close=Mock())
        body = dict(id='e'*32, captureEpoch='f'*32, width=1920, height=1080, sceneConfirmed=True,
                    expectedSource=public_source(selected))
        with patch.object(self.workspace, 'status', return_value=dict(phase='ready')), \
             patch('scripts.pilot.route_workspace.resource_checkpoint'), \
             patch('scripts.pilot.route_preparation_source.attempt_source',
                   side_effect=[selected, selected, ValueError('source_changed_during_load')]), \
             patch('motor_worker.route_reference_lk.ReferenceLKRoute.load', return_value=route), \
             patch('motor_worker.route_confirmation.ReferenceLKConfirmationLocalizer', return_value=tracker):
            with self.assertRaisesRegex(ValueError, 'source_changed_during_load'):
                self.workspace.start_live(self.job, body)
        tracker.close.assert_called_once()
        route.close.assert_called_once()
        self.assertIsNone(self.workspace.live)

    def test_failed_walk_install_or_archive_retires_and_closes_new_runtime(self):
        for archive_failure in (False, True):
            with self.subTest(archive_failure=archive_failure):
                route = types.SimpleNamespace(source_seconds=(0., 1.), close=Mock())
                tracker = types.SimpleNamespace(route=route, close=Mock())
                identity = ('e' if archive_failure else 'd')*32
                body = dict(id=identity, captureEpoch='f'*32, width=1920, height=1080,
                    sceneConfirmed=True, footCameraAssumptionConfirmed=True, diagnosticFrames=archive_failure,
                    clientVersion='walk_live_v8')
                def opened(*args, **kwargs):
                    self.workspace.live = dict(id=identity, tracker=tracker, geometry_sha256='0'*64)
                def installed(**kwargs):
                    if not archive_failure:
                        raise ValueError('install_failed')
                    self.workspace.live['walk'] = types.SimpleNamespace(max_seconds=120)
                with patch.object(self.workspace, 'start_live', side_effect=opened), \
                     patch.object(self.workspace, '_install_walk', side_effect=installed), \
                     patch('scripts.pilot.walk_diagnostics.WalkFrameArchive', side_effect=ValueError('archive_failed')):
                    with self.assertRaisesRegex(ValueError, 'install_failed|archive_failed'):
                        self.workspace.start_walk(self.job, body)
                tracker.close.assert_called_once()
                route.close.assert_called_once()
                self.assertIsNone(self.workspace.live)
                self.assertIn(identity, self.workspace.retired)


if __name__ == '__main__':
    unittest.main()
