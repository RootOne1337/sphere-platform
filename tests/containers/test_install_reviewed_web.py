"""Installer planning boundaries; no real Docker, GitHub or device commands."""
import copy
import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.pilot import install_reviewed_web as installer  # noqa: E402

SOURCE = "a" * 40
TAG = f"sphere-review-frontend:{SOURCE}"
IMAGE_ID = "sha256:" + "b" * 64


def config():
    return {"name": installer.PROJECT, "services": {
        "review-ui": {"image": "previous:image", "environment": {"API_URL": "http://backend:8000"}},
        "review-gateway": {"ports": [{"published": "3015", "host_ip": "127.0.0.1"}]}},
        "networks": {"review": {"internal": True}}}


def healthy_ui_host():
    return {'system': 'Windows', 'availableRamBytes': 6 * installer.GIB, 'totalRamBytes': 48 * installer.GIB,
            'committedBytes': 86 * installer.GIB, 'commitLimitBytes': 100 * installer.GIB,
            'freeDiskBytes': 35 * installer.GIB, 'volumeHealthStatus': 'Healthy',
            'volumeOperationalStatus': ['OK']}


class InstallTests(unittest.TestCase):
    def mocked_hosted_install(self, *, deferred=None, findings=None, bounded=False,
                              snapshots=None, cap_overrides=None, expected_failure=None, fresh_cap_overrides=None):
        """Exercise execute through healthy installation; every command is fake."""
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            root = Path(temporary).resolve()
            private = root / '.local-pilot'
            artifact = private / 'artifact'
            artifact.mkdir(parents=True)
            compose = private / 'baseline.json'
            compose.write_text('{}')
            old = config()
            if bounded:
                old['services']['review-ui'].update(mem_limit=str(768 * 1024**2), cpus=1)
            new = copy.deepcopy(old)
            new['services']['review-ui']['image'] = TAG
            before = {installer.UI: {'id': 'old-ui', 'imageId': 'old-image', 'imageTag': 'previous:image'}}
            after = {installer.UI: {'id': 'new-ui', 'imageId': IMAGE_ID, 'imageTag': TAG}}
            labels = {'com.docker.compose.project': installer.PROJECT,
                      'com.docker.compose.service': 'review-ui',
                      'com.docker.compose.project.config_files': str(compose)}
            current = {'Id': 'old-ui', 'Config': {'Env': ['API_URL=http://backend:8000'], 'Labels': labels}}
            if bounded:
                current['HostConfig'] = dict(Memory=768 * 1024**2, MemorySwap=1536 * 1024**2,
                                             NanoCpus=10**9) | (cap_overrides or {})
            installed = {'Id': 'new-ui', 'Image': IMAGE_ID, 'State': {'Health': {'Status': 'healthy'}}}
            fresh_current = copy.deepcopy(current)
            if fresh_cap_overrides:
                fresh_current['HostConfig'].update(fresh_cap_overrides)
            calls = []

            def command(args, **kwargs):
                calls.append(args)
                if args[-3:] == ['config', '--format', 'json']:
                    return json.dumps(new if args.count('--file') == 2 else old)
                if args[:3] == ['docker', 'image', 'load']:
                    return 'loaded'
                if args[:3] == ['docker', 'image', 'inspect']:
                    return json.dumps([{'Id': IMAGE_ID}])
                if args[-1:] == ['review-ui'] and 'up' in args:
                    return 'installed'
                self.fail(f'Unexpected command in mocked install: {args}')

            patches = {
                'ROOT': root, 'PRIVATE': private,
                'admit_candidate': MagicMock(return_value={'imageTag': TAG, 'imageId': IMAGE_ID,
                                                          'runId': 123, 'archiveBytes': 100}),
                'bounded_json': MagicMock(return_value={'runId': 123}),
                'check_ci': MagicMock(),
                'collect': MagicMock(side_effect=snapshots) if snapshots is not None else
                           MagicMock(return_value=healthy_ui_host() if bounded else {}),
                'evaluate': MagicMock(wraps=installer.evaluate) if bounded else MagicMock(return_value=findings or []),
                'snapshot': MagicMock(side_effect=[before, before, before, after]),
                'inspect': MagicMock(side_effect=[current, fresh_current, fresh_current, current, installed]
                                    if bounded else [current, current, installed]),
                'command': MagicMock(side_effect=command),
                'catalog_hash': MagicMock(return_value='catalog-digest'),
                'loaded_image_id': MagicMock(return_value=IMAGE_ID),
            }
            for name, value in patches.items():
                stack.enter_context(patch.object(installer, name, value))
            retention = stack.enter_context(patch('scripts.pilot.reviewed_artifact_retention.post_install',
                return_value={'state': 'completed', 'archivesRemoved': 2, 'imagesRemoved': 1}))
            response = MagicMock()
            response.__enter__.return_value.status = 200
            stack.enter_context(patch.object(installer.urllib.request, 'urlopen', return_value=response))
            options = {} if deferred is None else {'defer_cache_retention': deferred}
            if bounded:
                options['bounded_ui_resources'] = True
            failure = expected_failure or ('Host not admitted' if findings else None)
            if failure:
                with self.assertRaisesRegex(ValueError, failure):
                    installer.execute(artifact, SOURCE, IMAGE_ID, apply=True, **options)
                result = None
            else:
                result = installer.execute(artifact, SOURCE, IMAGE_ID, apply=True, **options)
                receipt = json.loads((Path(result['reportDirectory']) / 'installed.json').read_text('utf8'))
                self.assertEqual(receipt, result)
            return result, calls, retention, patches, root

    def test_bounded_profile_admits_ui_budget_and_records_three_fresh_checks_without_retention(self):
        snapshots = [healthy_ui_host() | {'observedAt': f'sample-{n}'} for n in range(3)]
        result, calls, retention, mocks, _root = self.mocked_hosted_install(
            bounded=True, deferred=True, snapshots=snapshots)
        self.assertTrue(result['runtimeInstalled'])
        self.assertEqual(result['resourceProfile'], {'kind': 'bounded_ui_install_v1',
            'minRamGiB': 4, 'minDiskGiB': 20, 'maxCommitPercent': 90, 'minAbsoluteCommitGiB': 4,
            'healthyVolumeRequired': True, 'daemonImporterHardBound': False})
        self.assertEqual([r['stage'] for r in result['resourceChecks']], ['planning', 'before-load', 'before-swap'])
        self.assertEqual([r['snapshot'] for r in result['resourceChecks']], snapshots)
        self.assertTrue(all(r['uiCaps']['memoryBytes'] == 768*1024**2 for r in result['resourceChecks']))
        self.assertEqual(mocks['collect'].call_count, 3)
        mocks['check_ci'].assert_called_once()
        mocks['loaded_image_id'].assert_called_once()
        retention.assert_not_called()
        self.assertEqual(result['cacheRetention']['state'], 'deferred')
        self.assertEqual(sum(args[:3] == ['docker', 'image', 'load'] for args in calls), 1)
        self.assertEqual(sum('up' in args for args in calls), 1)

    def test_default_profile_still_rejects_eighty_six_percent_commit(self):
        host = healthy_ui_host()
        self.assertIn('commit_headroom_low', installer.resource_findings(host, False))
        self.assertEqual(installer.resource_findings(host, True), [])
        self.assertEqual(installer.resource_profile(False)['maxCommitPercent'], 85)

    def test_bounded_profile_refuses_low_or_unknown_resources(self):
        cases = [({'availableRamBytes': 4*installer.GIB-1}, 'ram_headroom_low'),
                 ({'committedBytes': 90*installer.GIB}, 'commit_headroom_low'),
                 ({'committedBytes': 7*installer.GIB, 'commitLimitBytes': 10*installer.GIB}, 'commit_headroom_low'),
                 ({'freeDiskBytes': 20*installer.GIB-1}, 'disk_headroom_low'),
                 ({'volumeHealthStatus': 'Warning'}, 'volume_not_ready'),
                 ({'volumeOperationalStatus': []}, 'volume_health_unavailable'),
                 ({'committedBytes': None}, 'commit_measurement_unavailable'),
                 ({'system': 'Linux'}, 'bounded_ui_windows_counters_required')]
        for change, reason in cases:
            with self.subTest(change=change):
                self.assertIn(reason, installer.resource_findings(healthy_ui_host() | change, True))

    def test_bounded_profile_refuses_missing_excessive_or_unresolved_effective_caps(self):
        for caps in ({'Memory': 0}, {'Memory': 2*installer.GIB}, {'MemorySwap': -1},
                     {'MemorySwap': 3*installer.GIB}, {'NanoCpus': 0}, {'NanoCpus': 2*10**9},
                     {'Memory': None}, {'Memory': 512*1024**2}):
            with self.subTest(caps=caps):
                _result, calls, retention, mocks, _root = self.mocked_hosted_install(
                    bounded=True, cap_overrides=caps, expected_failure='resource caps')
                self.assertTrue(all(args[-3:] == ['config', '--format', 'json'] for args in calls))
                mocks['loaded_image_id'].assert_not_called()
                retention.assert_not_called()

    def test_bounded_profile_fresh_second_and_third_guard_still_prevent_load_or_swap(self):
        good = healthy_ui_host()
        low = good | {'availableRamBytes': 3*installer.GIB}
        for at, message in ((1, 'before image load'), (2, 'before UI replacement')):
            with self.subTest(stage=at):
                samples = [good.copy() for _ in range(at)] + [low]
                _result, calls, retention, mocks, _root = self.mocked_hosted_install(
                    bounded=True, deferred=True, snapshots=samples, expected_failure=message)
                self.assertEqual(sum(args[:3] == ['docker', 'image', 'load'] for args in calls), at-1)
                self.assertFalse(any('up' in args for args in calls))
                self.assertEqual(mocks['collect'].call_count, at+1)
                retention.assert_not_called()

    def test_bounded_profile_cannot_combine_with_degraded_volume(self):
        with patch.object(installer, 'admit_candidate') as admit, patch.object(installer, 'command') as command:
            with self.assertRaisesRegex(ValueError, 'degraded-volume exception is incompatible'):
                installer.execute(Path('unused'), SOURCE, IMAGE_ID, apply=True,
                    bounded_ui_resources=True, allow_degraded_volume=True)
        admit.assert_not_called()
        command.assert_not_called()

    def test_bounded_profile_rechecks_effective_caps_before_loading_image(self):
        _result, calls, retention, _mocks, _root = self.mocked_hosted_install(
            bounded=True, fresh_cap_overrides={'Memory': 0}, expected_failure='resource caps')
        self.assertFalse(any(args[:3] == ['docker', 'image', 'load'] or 'up' in args for args in calls))
        retention.assert_not_called()

    def test_bounded_caps_require_matching_owner_and_unchanged_resolved_service(self):
        old = config()
        old['services']['review-ui'].update(mem_limit=str(768*1024**2), cpus=1)
        candidate = copy.deepcopy(old)
        candidate['services']['review-ui']['image'] = TAG
        current = {'Config': {'Labels': {'com.docker.compose.project': installer.PROJECT,
                                        'com.docker.compose.service': 'review-ui'}},
                   'HostConfig': {'Memory': 768*1024**2, 'MemorySwap': 1536*1024**2, 'NanoCpus': 10**9}}
        installer.bounded_ui_caps(current, old, candidate)
        for broken in ({}, current | {'HostConfig': None}, current | {'Config': {'Labels': {}}}):
            with self.subTest(broken=broken), self.assertRaises(ValueError):
                installer.bounded_ui_caps(broken, old, candidate)
        candidate['services']['review-ui']['mem_limit'] = str(installer.GIB)
        with self.assertRaisesRegex(ValueError, 'candidate configuration changed'):
            installer.bounded_ui_caps(current, old, candidate)

    def test_hosted_deferred_retention_preserves_admission_load_install_and_previous_image(self):
        result, calls, retention, mocks, root = self.mocked_hosted_install(deferred=True)
        retention.assert_not_called()
        self.assertEqual(result['cacheRetention'], {'state': 'deferred', 'reason': 'operator_requested',
            'archivesRemoved': 0, 'imagesRemoved': 0, 'previousImagePreserved': True})
        self.assertTrue(result['runtimeInstalled'])
        self.assertTrue(result['cacheRetentionDeferred'])
        mocks['admit_candidate'].assert_called_once()
        mocks['check_ci'].assert_called_once()
        self.assertEqual(mocks['collect'].call_count, 3)
        self.assertEqual(mocks['evaluate'].call_count, 3)
        mocks['loaded_image_id'].assert_called_once()
        self.assertEqual(sum(args[:3] == ['docker', 'image', 'load'] for args in calls), 1)
        self.assertEqual(sum('up' in args for args in calls), 1)

    def test_hosted_retention_default_is_unchanged(self):
        result, _calls, retention, _mocks, root = self.mocked_hosted_install()
        retention.assert_called_once_with(root, SOURCE, 'old-image')
        self.assertFalse(result['cacheRetentionDeferred'])
        self.assertEqual(result['cacheRetention']['state'], 'completed')

    def test_deferred_retention_cannot_bypass_resource_admission_or_mutate_images(self):
        _result, calls, retention, mocks, _root = self.mocked_hosted_install(
            deferred=True, findings=['commit_headroom_low'])
        retention.assert_not_called()
        mocks['admit_candidate'].assert_called_once()
        mocks['check_ci'].assert_called_once()
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(args[-3:] == ['config', '--format', 'json'] for args in calls))
        mocks['loaded_image_id'].assert_not_called()

    def test_deferred_retention_does_not_bypass_hosted_ci_admission(self):
        with patch.object(installer, 'private_path', return_value=Path('unused')), \
                patch.object(installer, 'admit_candidate', return_value={'imageId': IMAGE_ID}), \
                patch.object(installer, 'bounded_json', return_value={}), \
                patch.object(installer, 'check_ci', side_effect=ValueError('CI run not admitted')), \
                patch.object(installer, 'collect') as collect, patch.object(installer, 'command') as command, \
                patch('scripts.pilot.reviewed_artifact_retention.post_install') as retention:
            with self.assertRaisesRegex(ValueError, 'CI run not admitted'):
                installer.execute(Path('unused'), SOURCE, IMAGE_ID, apply=True, defer_cache_retention=True,
                                  bounded_ui_resources=True)
        collect.assert_not_called()
        command.assert_not_called()
        retention.assert_not_called()

    def test_cli_explicitly_passes_cache_retention_deferral(self):
        args = ['installer', '--artifact', 'unused', '--source', SOURCE,
                '--expected-image-id', IMAGE_ID, '--apply', '--defer-cache-retention', '--bounded-ui-resources']
        with patch.object(sys, 'argv', args), patch.object(installer, 'execute', return_value={}) as execute, \
                patch('builtins.print'):
            self.assertEqual(installer.main(), 0)
        self.assertTrue(execute.call_args.kwargs['defer_cache_retention'])
        self.assertTrue(execute.call_args.kwargs['bounded_ui_resources'])

    def test_frozen_install_without_environment_metadata_does_not_guess_env_file(self):
        self.assertEqual(installer.compose_prefix({}), ["docker", "compose", "--project-name", installer.PROJECT])

    def test_explicit_environment_metadata_remains_private_and_mandatory(self):
        key = "com.docker.compose.project.environment_file"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            private = root / ".local-pilot"
            private.mkdir()
            env = private / "explicit.env"
            env.write_text("FAKE_SECRET=preserved\n")
            outside = root / "outside.env"
            outside.write_text("")
            with patch.object(installer, "ROOT", root), patch.object(installer, "PRIVATE", private):
                self.assertEqual(installer.compose_prefix({key: str(env)}),
                                 ["docker", "compose", "--project-name", installer.PROJECT, "--env-file", str(env)])
                for invalid in (str(outside), str(private / "missing.env"), "", None):
                    with self.subTest(invalid=invalid), self.assertRaises((ValueError, OSError)):
                        installer.compose_prefix({key: invalid})

    def test_resolved_baseline_without_env_label_reaches_plan_without_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            private = root / ".local-pilot"
            private.mkdir()
            artifact = private / "artifact"
            artifact.mkdir()
            compose = private / "baseline.json"
            compose.write_text("{}")
            old = config()
            old["services"]["review-ui"]["environment"]["FAKE_SECRET"] = "literal-$value-${name}"
            new = copy.deepcopy(old)
            new["services"]["review-ui"]["image"] = TAG
            before = {installer.UI: {"id": "old-ui", "imageId": "old-image", "imageTag": "previous:image"}}
            current = {"Id": "old-ui", "Config": {"Env": [f"{key}={value}" for key, value in
                old["services"]["review-ui"]["environment"].items()], "Labels": {
                "com.docker.compose.project": installer.PROJECT, "com.docker.compose.service": "review-ui",
                "com.docker.compose.project.config_files": str(compose)}}}
            calls = []

            def command(args, **kwargs):
                calls.append(args)
                self.assertNotIn("--env-file", args)
                self.assertEqual(args[-3:], ["config", "--format", "json"])
                return json.dumps(new if args.count("--file") == 2 else old)

            with patch.object(installer, "ROOT", root), patch.object(installer, "PRIVATE", private), \
                    patch.object(installer, "admit_candidate", return_value={"imageTag": TAG, "imageId": IMAGE_ID,
                        "runId": 123, "archiveBytes": 0}), patch.object(installer, "collect", return_value={}), \
                    patch.object(installer, "evaluate", return_value=[]), patch.object(installer, "snapshot", return_value=before), \
                    patch.object(installer, "inspect", return_value=current), patch.object(installer, "command", side_effect=command), \
                    patch.object(installer, "catalog_hash", return_value="catalog-digest"):
                result = installer.execute(artifact, SOURCE, IMAGE_ID, apply=False, local_execution=True)
            self.assertFalse(result["runtimeInstalled"])
            self.assertEqual(len(calls), 3)  # Read baseline, roundtrip, candidate; never load/up/stop.
            frozen = json.loads((Path(result["reportDirectory"]) / "baseline.json").read_text())
            self.assertEqual(frozen["services"]["review-ui"]["environment"]["FAKE_SECRET"], "literal-$$value-$${name}")

    def test_frozen_compose_preserves_literal_dollars_and_uses_one_baseline(self):
        old = config()
        old["services"]["review-ui"]["environment"]["FAKE_SECRET"] = "literal-$value-${name}"
        old["services"]["review-ui"]["entrypoint"] = ["sh", "-c", "echo $$SHELL_VALUE"]
        old["services"]["review-ui"]["healthcheck"] = {"test": ["CMD-SHELL", "echo $$HEALTH_VALUE"]}
        with tempfile.TemporaryDirectory() as directory, patch.object(installer, "command", return_value=json.dumps(old)) as command:
            path = Path(directory) / "baseline.json"
            result = installer.freeze_compose(["docker", "compose", "--project-name", installer.PROJECT], old, path)
            self.assertEqual(result[-2:], ["--file", str(path)])
            self.assertEqual(result.count("--file"), 1)
            self.assertEqual(json.loads(path.read_text())["services"]["review-ui"]["environment"]["FAKE_SECRET"], "literal-$$value-$${name}")
            self.assertEqual(json.loads(path.read_text())["services"]["review-ui"]["entrypoint"], old["services"]["review-ui"]["entrypoint"])
            self.assertEqual(json.loads(path.read_text())["services"]["review-ui"]["healthcheck"], old["services"]["review-ui"]["healthcheck"])
            command.assert_called_once_with(result + ["config", "--format", "json"])

    def test_frozen_compose_rejects_any_roundtrip_change_before_image_load(self):
        old = config()
        changed = copy.deepcopy(old)
        changed["networks"]["review"]["internal"] = False
        with tempfile.TemporaryDirectory() as directory, patch.object(installer, "command", return_value=json.dumps(changed)):
            with self.assertRaisesRegex(ValueError, "Frozen Compose differs"):
                installer.freeze_compose(["docker", "compose"], old, Path(directory) / "baseline.json")

    def test_classic_loaded_id_matches_admitted_config(self):
        self.assertEqual(installer.loaded_image_id(Path("unused"), {"Id": IMAGE_ID}, IMAGE_ID), IMAGE_ID)

    def test_containerd_loaded_manifest_must_bind_admitted_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json",
                        "config": {"digest": IMAGE_ID}}
            payload = json.dumps(manifest).encode()
            manifest_id = "sha256:" + hashlib.sha256(payload).hexdigest()
            with tarfile.open(directory / "image.tar.gz", "w:gz") as bundle:
                entry = tarfile.TarInfo("blobs/sha256/" + manifest_id.removeprefix("sha256:"))
                entry.size = len(payload)
                bundle.addfile(entry, io.BytesIO(payload))
            image = {"Id": manifest_id, "Descriptor": {"digest": manifest_id, "mediaType": manifest["mediaType"]}}
            self.assertEqual(installer.loaded_image_id(directory, image, IMAGE_ID), manifest_id)
            with self.assertRaises(ValueError):
                installer.loaded_image_id(directory, image, "sha256:" + "c" * 64)
            with self.assertRaises(ValueError):
                installer.loaded_image_id(directory, image | {"Descriptor": {"digest": IMAGE_ID}}, IMAGE_ID)
            for descriptor in (None, [], "invalid"):
                with self.subTest(descriptor=descriptor), self.assertRaises(ValueError):
                    installer.loaded_image_id(directory, image | {"Descriptor": descriptor}, IMAGE_ID)
            other_id = "sha256:" + "d" * 64
            with self.assertRaises(ValueError):
                installer.loaded_image_id(directory, {"Id": other_id, "Descriptor": {"digest": other_id,
                    "mediaType": manifest["mediaType"]}}, IMAGE_ID)

    def test_containerd_manifest_content_must_match_loaded_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            payload = json.dumps({"schemaVersion": 2, "config": {"digest": IMAGE_ID}}).encode()
            with tarfile.open(directory / "image.tar.gz", "w:gz") as bundle:
                entry = tarfile.TarInfo("blobs/sha256/" + "e" * 64)
                entry.size = len(payload)
                bundle.addfile(entry, io.BytesIO(payload))
            actual = "sha256:" + "e" * 64
            with self.assertRaises(ValueError):
                installer.loaded_image_id(directory, {"Id": actual, "Descriptor": {"digest": actual,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json"}}, IMAGE_ID)

    def test_containerd_manifest_rejects_invalid_json_shapes(self):
        media_type = "application/vnd.oci.image.manifest.v1+json"
        for manifest in ([], None, {"schemaVersion": 2, "mediaType": media_type, "config": []},
                         {"schemaVersion": 2, "mediaType": media_type, "config": None}):
            with self.subTest(manifest=manifest), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                payload = json.dumps(manifest).encode()
                actual = "sha256:" + hashlib.sha256(payload).hexdigest()
                with tarfile.open(directory / "image.tar.gz", "w:gz") as bundle:
                    entry = tarfile.TarInfo("blobs/sha256/" + actual.removeprefix("sha256:"))
                    entry.size = len(payload)
                    bundle.addfile(entry, io.BytesIO(payload))
                with self.assertRaises(ValueError):
                    installer.loaded_image_id(directory, {"Id": actual, "Descriptor": {
                        "digest": actual, "mediaType": media_type}}, IMAGE_ID)

    def test_accepts_only_the_ui_image_delta(self):
        old = config()
        old["services"]["review-ui"]["build"] = {"context": "old-checkout", "args": {"BUILD_SHA": "old"}}
        new = copy.deepcopy(old)
        new["services"]["review-ui"]["image"] = TAG
        del new["services"]["review-ui"]["build"]
        installer.validate_delta(old, new, TAG)
        self.assertEqual(old["services"]["review-ui"]["image"], "previous:image")

    def test_rejects_environment_service_network_and_port_changes(self):
        changes = [lambda c: c["services"]["review-ui"]["environment"].update(API_URL="http://other"),
                   lambda c: c["services"].update(backend={"image": "other"}),
                   lambda c: c["networks"]["review"].update(internal=False),
                   lambda c: c["services"]["review-ui"].update(build={"context": "old-checkout"}),
                   lambda c: c["services"]["review-gateway"]["ports"][0].update(host_ip="0.0.0.0"),
                   lambda c: c["services"]["review-ui"].update(ports=[{"published": "3000"}])]
        for change in changes:
            with self.subTest(change=change):
                old = config()
                new = copy.deepcopy(old)
                new["services"]["review-ui"]["image"] = TAG
                change(new)
                with self.assertRaises(ValueError):
                    installer.validate_delta(old, new, TAG)

    def test_even_unchanged_public_gateway_cannot_be_admitted(self):
        for ports in ([{"published": "3015", "host_ip": "0.0.0.0"}],
                      [{"published": "9999", "host_ip": "127.0.0.1"}]):
            with self.subTest(ports=ports):
                old = config()
                old["services"]["review-gateway"]["ports"] = ports
                new = copy.deepcopy(old)
                new["services"]["review-ui"]["image"] = TAG
                with self.assertRaises(ValueError):
                    installer.validate_delta(old, new, TAG)

    def test_preserves_every_other_container_identity_epoch_and_state(self):
        before = {installer.UI: {"id": "old"}, "api": {"id": "api", "startedAt": "epoch", "status": "running"}}
        after = copy.deepcopy(before)
        after[installer.UI] = {"id": "new"}
        installer.preserved(before, after)
        for field in ("id", "startedAt", "status"):
            changed = copy.deepcopy(after)
            changed["api"][field] = "different"
            with self.assertRaises(ValueError):
                installer.preserved(before, changed)
        with self.assertRaises(ValueError):
            installer.preserved(before, after | {"new-container": {}})

    def test_github_run_attempt_revision_workflow_and_conclusion_are_independent(self):
        receipt = {"runId": 123, "runAttempt": 1, "sourceRevision": SOURCE}
        run = {"head_sha": SOURCE, "run_attempt": 1, "path": ".github/workflows/ci-frontend.yml",
               "name": "CI — Frontend", "status": "completed", "conclusion": "success"}
        with patch.object(installer, "command", return_value=json.dumps(run)):
            installer.check_ci(receipt)
        for field, value in (("head_sha", "b" * 40), ("run_attempt", 2), ("path", "other.yml"),
                             ("name", "Other"), ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(field=field):
                with patch.object(installer, "command", return_value=json.dumps(run | {field: value})):
                    with self.assertRaises(ValueError):
                        installer.check_ci(receipt)

    def test_warning_volume_prevents_load_up_stop_and_rollback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / ".local-pilot"
            private.mkdir()
            artifact = private / "artifact"
            artifact.mkdir()
            compose = private / "compose.json"
            compose.write_text("{}")
            env = private / ".env"
            env.write_text("")
            old = config()
            new = copy.deepcopy(old)
            new["services"]["review-ui"]["image"] = TAG
            before = {installer.UI: {"id": "old-ui", "imageId": "old-image", "imageTag": "previous:image"}}
            current = {"Id": "old-ui", "Config": {"Env": ["API_URL=http://backend:8000"], "Labels": {
                "com.docker.compose.project": installer.PROJECT, "com.docker.compose.service": "review-ui",
                "com.docker.compose.project.config_files": str(compose),
                "com.docker.compose.project.environment_file": str(env)}}}
            host = {"system": "Windows", "freeDiskBytes": 30 * 1024**3, "totalRamBytes": 32 * 1024**3,
                    "availableRamBytes": 8 * 1024**3, "committedBytes": 30 * 1024**3, "commitLimitBytes": 60 * 1024**3,
                    "volumeHealthStatus": "Warning", "volumeOperationalStatus": ["Full Repair Needed"]}
            calls = []

            def command(args, **kwargs):
                calls.append(args)
                self.assertEqual(args[:2], ["docker", "compose"])
                self.assertEqual(args[-3:], ["config", "--format", "json"])
                return json.dumps(new if args.count("--file") == 2 else old)

            with patch.object(installer, "ROOT", root), patch.object(installer, "PRIVATE", private), \
                    patch.object(installer, "admit", return_value={"imageTag": TAG, "imageId": IMAGE_ID, "runId": 123, "archiveBytes": 100}), \
                    patch.object(installer, "bounded_json", return_value={}), patch.object(installer, "check_ci"), \
                    patch.object(installer, "collect", return_value=host), patch.object(installer, "snapshot", return_value=before), \
                    patch.object(installer, "inspect", return_value=current), patch.object(installer, "command", side_effect=command), \
                    patch.object(installer, "catalog_hash", return_value="catalog-digest"):
                with self.assertRaisesRegex(ValueError, "Host not admitted"):
                    installer.execute(artifact, SOURCE, IMAGE_ID, apply=True)
                self.assertEqual(len(calls), 3)
                calls.clear()
                # The authorized volume warning must not mask a later RAM drop.
                with patch.object(installer, "collect", side_effect=[host, host | {"availableRamBytes": 1}]), \
                        self.assertRaisesRegex(ValueError, "Host changed before image load"):
                    installer.execute(artifact, SOURCE, IMAGE_ID, apply=True, allow_degraded_volume=True)
            self.assertEqual(len(calls), 3)  # baseline, frozen roundtrip, candidate; no runtime mutation
            plans = list(private.glob("reviewed-web-install-*/plan.json"))
            self.assertEqual(len(plans), 2)
            recorded = [json.loads(plan.read_text()) for plan in plans]
            self.assertTrue(all(not plan["runtimeInstalled"] for plan in recorded))
            self.assertTrue(all(plan["resourceFindings"] == ["volume_not_ready"] for plan in recorded))
            exception = next(plan for plan in recorded if plan["volumeExceptionRequested"])
            self.assertEqual(exception["admissionFindings"], [])
            self.assertTrue(exception["volumeExceptionApplied"])

    def test_self_reported_image_id_cannot_replace_independent_ci_admission(self):
        for deferred in (False, True):
            for bounded in (False, True):
                with self.subTest(deferred=deferred,bounded=bounded), patch.object(installer, "private_path", return_value=Path("unused")), \
                        patch.object(installer, "admit", return_value={"imageId": "sha256:" + "c" * 64}), \
                        patch.object(installer, "command") as command:
                    with self.assertRaisesRegex(ValueError, "independent CI admission"):
                        installer.execute(Path("unused"), SOURCE, IMAGE_ID, apply=True,
                                          defer_cache_retention=deferred, bounded_ui_resources=bounded)
                    command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
