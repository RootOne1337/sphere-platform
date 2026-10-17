"""The local CI reporter must never publish ambiguous or stale results as green."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import local_ci as ci


class LocalCISourceContentTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.file = self.root / 'android/source.kt'
        self.file.parent.mkdir()
        self.file.write_bytes(b'package fixture\n')
        for args in [['init', '-q'], ['config', 'core.autocrlf', 'false'],
                     ['add', 'android/source.kt'],
                     ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                      'commit', '-qm', 'source fixture']]:
            subprocess.run(['git', *args], cwd=self.root, check=True, capture_output=True)
        self.sha = ci.git(self.root, 'rev-parse', 'HEAD')

    def test_clean_source_bytes_are_accepted(self):
        ci.same_component(self.root, self.sha, ['android'])

    def test_cached_clean_diff_does_not_hide_same_size_content_damage(self):
        previous = self.file.stat()
        self.file.write_bytes(b'\xff' * previous.st_size)
        os.utime(self.file, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        real_git = ci.git

        def cached_git(root, *args):
            if args[0] in {'diff', 'ls-files'}:
                return ''  # Reproduce a stat-cache falsely reporting no change.
            return real_git(root, *args)

        with patch.object(ci, 'git', side_effect=cached_git):
            with self.assertRaisesRegex(ci.Refused, 'component_content_mismatch'):
                ci.same_component(self.root, self.sha, ['android'])


class LocalCIResultsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_process_failure_is_not_success_even_with_output(self):
        result = ci.run_step([sys.executable, "-c", "print('ok'); raise SystemExit(7)"],
                             self.root, dict(os.environ), self.root / "test.log")
        self.assertEqual(result["exitCode"], 7)
        self.assertFalse(result["timedOut"])

    def test_timeout_stops_child_instead_of_green(self):
        result = ci.run_step([sys.executable, "-c", "import time; time.sleep(30)"],
                             self.root, dict(os.environ), self.root / "test.log", timeout=1)
        self.assertTrue(result["timedOut"])
        self.assertNotEqual(result["exitCode"], 0)

    def test_log_limit_drains_without_hanging_or_unbounded_disk(self):
        with patch.object(ci, "LOG_LIMIT", 4096):
            result = ci.run_step([sys.executable, "-c", "import sys; sys.stdout.write('a'*1048576)"],
                                 self.root, dict(os.environ), self.root / "test.log")
        self.assertEqual(result["exitCode"], 0)
        self.assertTrue(result["logTruncated"])
        self.assertEqual((self.root / "test.log").stat().st_size, 4096)

    def test_failed_log_sink_is_not_success(self):
        with self.assertRaisesRegex(ci.Refused, "local_log_write_failed"):
            ci.run_step([sys.executable, "-c", "print('done')"], self.root,
                        dict(os.environ), self.root / "missing/test.log")

    def test_jest_zero_tests_stale_or_inconsistent_report_refused(self):
        file = self.root / "jest.json"
        base = {"numTotalTests": 1, "numPassedTests": 1, "numFailedTests": 0,
                "numPendingTests": 0, "numTotalTestSuites": 1,
                "numFailedTestSuites": 0, "success": True}
        for update in [{"numTotalTests": 0, "numPassedTests": 0},
                       {"numTotalTests": 2}, {"numTotalTests": True}, {"success": "true"}]:
            with self.subTest(update=update):
                file.write_text(json.dumps(base | update))
                with self.assertRaises(ci.Refused):
                    ci.jest_counts(file, time.time() - 1)
        file.write_text(json.dumps(base))
        with self.assertRaisesRegex(ci.Refused, "stale"):
            ci.jest_counts(file, time.time() + 10)
        self.assertEqual(ci.jest_counts(file, time.time() - 1)["passed"], 1)

    def test_junit_records_executed_failures_and_skips(self):
        file = self.root / "tests.xml"
        file.write_text('<testsuite tests="3"><testcase/><testcase><failure/></testcase><testcase><skipped/></testcase></testsuite>')
        self.assertEqual(ci.junit_counts([file], time.time() - 1),
                         {"tests": 3, "failures": 1, "errors": 0, "skipped": 1})

    def test_empty_all_skipped_and_xml_entities_refused(self):
        file = self.root / "tests.xml"
        for raw in ['<testsuite/>', '<testsuite><testcase><skipped/></testcase></testsuite>',
                    '<!DOCTYPE doc [<!ENTITY x SYSTEM "file:///etc/passwd">]><testsuite/>']:
            with self.subTest(raw=raw):
                file.write_text(raw)
                with self.assertRaises(ci.Refused):
                    ci.junit_counts([file], time.time() - 1)

    def test_source_requires_exact_commit_and_approved_repository(self):
        sha = "a" * 40
        with patch.object(ci, "git", side_effect=[sha, "", "https://github.com/outsider/fork.git"]):
            with self.assertRaisesRegex(ci.Refused, "repository_mismatch"):
                ci.validate_source(self.root, sha, "refs/heads/trusted")
        for value in ["HEAD", "abc", "A" * 40, "a" * 40 + ";bad"]:
            with self.subTest(value=value), self.assertRaises(ci.Refused):
                ci.validate_source(self.root, value, "refs/heads/trusted")

    def test_changed_or_untracked_component_refused(self):
        with patch.object(ci, "git", return_value="diff"):
            with self.assertRaisesRegex(ci.Refused, "component_source_changed"):
                ci.same_component(self.root, "a" * 40, ["android"])
        with patch.object(ci, "git", side_effect=["", "android/src/extra.kt"]):
            with self.assertRaises(ci.Refused):
                ci.same_component(self.root, "a" * 40, ["android"])

    def test_status_requires_remote_sha_and_exact_readback(self):
        sha = "a" * 40
        expected = {"id": 5, "state": "success", "context": ci.CONTEXTS["frontend"],
                    "description": "passed", "created_at": "now"}
        for commit, created, rows in [({"sha": "b" * 40}, expected, [expected]),
                                      ({"sha": sha}, expected, [expected | {"id": 6}]),
                                      ({"sha": sha}, expected, [expected | {"state": "pending"}]),
                                      ({"sha": sha}, expected, [])]:
            with self.subTest(commit=commit, rows=rows):
                with patch.object(ci, "github", side_effect=[commit, created, rows]):
                    with self.assertRaises(ci.Refused):
                        ci.publish(self.root, sha, "frontend", "success", "passed")
        with patch.object(ci, "github", side_effect=[{"sha": sha}, expected, [expected]]):
            self.assertTrue(ci.publish(self.root, sha, "frontend", "success", "passed")["readbackVerified"])

    def test_status_cannot_send_token_or_external_url(self):
        with patch.object(ci, "github") as api:
            with self.assertRaises(ci.Refused):
                ci.publish(self.root, "a" * 40, "frontend", "success", "passed", "https://elsewhere.invalid/report")
            api.assert_not_called()

    def test_child_does_not_inherit_operator_tokens_or_prod_urls(self):
        with patch.dict(os.environ, {"GH_TOKEN": "private", "GITHUB_TOKEN": "private",
                                     "POSTGRES_URL": "production", "SPHERE_ENROLLMENT_KEY": "private"}):
            env = ci.child_environment(self.root, "a" * 40)
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("SPHERE_ENROLLMENT_KEY", env)
        self.assertIn("sphere_audit_ci", env["POSTGRES_URL"])
        self.assertEqual(env["DEV_SKIP_AUTH"], "false")

    def test_windows_compose_plugin_search_keeps_system_directories(self):
        with patch.dict(os.environ, {"ProgramData": "system-data", "ProgramFiles": "system-programs"}):
            env = ci.child_environment(self.root, "a" * 40)
        values = {key.upper(): value for key, value in env.items()}
        self.assertEqual(values["PROGRAMDATA"], "system-data")
        self.assertEqual(values["PROGRAMFILES"], "system-programs")

    def test_retention_deletes_only_completed_marked_flat_run(self):
        runs = self.root / "runs"
        runs.mkdir()
        for name in ["20261012T120000Z-aaaaaaaa", "20261012T130000Z-bbbbbbbb"]:
            directory = runs / name
            directory.mkdir()
            (directory / "receipt.json").write_text(json.dumps({"schemaVersion": 1, "runId": name,
                "workflowMode": "maintainer-local-executor", "state": "success"}))
            (directory / "private.log").write_text("log")
        result = ci.retain_runs(self.root, keep=1)
        self.assertEqual(result["retainedRuns"], 1)
        self.assertFalse((runs / "20261012T120000Z-aaaaaaaa").exists())

    def test_unknown_or_active_run_not_deleted(self):
        runs = self.root / "runs"
        directory = runs / "20261012T120000Z-aaaaaaaa"
        directory.mkdir(parents=True)
        marker = {"schemaVersion": 1, "runId": directory.name,
                  "workflowMode": "maintainer-local-executor", "state": "running"}
        (directory / "receipt.json").write_text(json.dumps(marker))
        with self.assertRaisesRegex(ci.Refused, "reconciliation"):
            ci.retain_runs(self.root, keep=0)
        self.assertTrue(directory.exists())

    def android_output_run(self, state="success"):
        directory = self.root / "runs/20261012T140000Z-cccccccc"
        directory.mkdir(parents=True)
        marker = {"schemaVersion": 1, "runId": directory.name,
                  "workflowMode": "maintainer-local-executor", "state": state,
                  "profiles": {"android": {"state": state}}}
        (directory / "receipt.json").write_text(json.dumps(marker))
        reports = directory / "android-build/app/test-results/testDevDebugUnitTest"
        reports.mkdir(parents=True)
        (reports / "TEST-fixture.xml").write_text('<testsuite tests="1" failures="0" errors="0"/>')
        cache = directory / "gradle-project-cache/nested"
        cache.mkdir(parents=True)
        (cache / "derived.bin").write_bytes(b"derived")
        return directory, marker

    def test_android_derived_outputs_are_removed_but_reports_and_results_survive(self):
        import zipfile
        directory, _ = self.android_output_run()
        result = ci.retain_runs(self.root)
        self.assertEqual(result["retainedRuns"], 1)
        self.assertFalse((directory / "android-build").exists())
        self.assertFalse((directory / "gradle-project-cache").exists())
        self.assertEqual(json.loads((directory / "receipt.json").read_text())["state"], "success")
        with zipfile.ZipFile(directory / "android-final-junit.zip") as archive:
            self.assertEqual(archive.namelist(), ["testDevDebugUnitTest/TEST-fixture.xml"])
            self.assertIn(b'tests="1"', archive.read(archive.namelist()[0]))
        self.assertEqual(ci.retain_runs(self.root)["retainedRuns"], 1)

    def test_android_active_or_wrong_marker_never_discards_outputs(self):
        directory, marker = self.android_output_run(state="running")
        for bad in [marker, marker | {"state": "success", "runId": "other"},
                    marker | {"state": "success", "profiles": {}},
                    marker | {"state": "success", "workflowMode": "foreign"}]:
            with self.subTest(marker=bad):
                with self.assertRaisesRegex(ci.Refused, "marker_mismatch"):
                    ci.cleanup_android_outputs(directory, bad)
                self.assertTrue((directory / "android-build").exists())

    def test_android_redirect_anywhere_refuses_entire_deletion_set(self):
        directory, marker = self.android_output_run()
        original = Path.is_symlink
        for name in ["android-build", "gradle-project-cache/nested/derived.bin"]:
            target = directory / name
            with self.subTest(path=name), patch.object(Path, "is_symlink", lambda path: str(path).removeprefix('\\\\?\\') == str(target) or original(path)):
                with self.assertRaisesRegex(ci.Refused, "android_output_redirected"):
                    ci.cleanup_android_outputs(directory, marker)
            self.assertTrue((directory / "android-build").exists())
            self.assertTrue((directory / "gradle-project-cache").exists())

    def test_android_cleanup_preserves_foreign_siblings_and_shared_cache(self):
        directory, marker = self.android_output_run()
        foreign = directory / "foreign-build"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("keep")
        shared = self.root / "shared-gradle-cache"
        shared.mkdir()
        (shared / "keep.bin").write_bytes(b"keep")
        ci.cleanup_android_outputs(directory, marker)
        self.assertTrue((foreign / "keep.txt").exists())
        self.assertTrue((shared / "keep.bin").exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended path behavior")
    def test_android_cleanup_handles_generated_names_beyond_max_path(self):
        directory, marker = self.android_output_run()
        long_directory = Path('\\\\?\\' + str(directory.resolve())) / 'android-build' / ('nested-' * 20) / ('generated-' * 15)
        long_directory.mkdir(parents=True)
        (long_directory / 'hilt-generated.java').write_text('derived')
        ci.cleanup_android_outputs(directory, marker)
        self.assertFalse((directory / 'android-build').exists())

    def test_lock_refuses_parallel_heavy_job(self):
        with ci.execution_lock(self.root / "execution.lock"):
            with self.assertRaisesRegex(ci.Refused, "another_local_ci_job"):
                with ci.execution_lock(self.root / "execution.lock"):
                    self.fail("lock incorrectly admitted a second job")


if __name__ == "__main__":
    unittest.main()
