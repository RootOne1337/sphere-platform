"""Remote forks and unpushed source must not schedule local host executions."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import local_ci as ci
from scripts.pilot import local_ci_watch as watch


class LocalCIQueueTest(unittest.TestCase):
    def test_volume_exception_is_off_unless_explicit_and_time_bounded(self):
        now = datetime(2026, 10, 13, tzinfo=timezone.utc)
        self.assertFalse(watch.volume_exception_authorized({}, now))
        self.assertTrue(watch.volume_exception_authorized({"volumeException": {
            "authorized": True, "expiresAtUtc": (now + timedelta(hours=2)).isoformat(),
        }}, now))
        for exception in [True, {}, {"authorized": "true"},
                          {"authorized": True, "expiresAtUtc": now.isoformat()},
                          {"authorized": True, "expiresAtUtc": (now + timedelta(days=2)).isoformat()},
                          {"authorized": True, "expiresAtUtc": "2026-10-13T01:00:00"},
                          {"authorized": True, "expiresAtUtc": "private-data"}]:
            with self.subTest(exception=exception), self.assertRaises(ci.Refused):
                watch.volume_exception_authorized({"volumeException": exception}, now)

    def test_queue_passes_only_a_valid_explicit_volume_exception(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            config = {"root": directory, "trustedRef": "refs/heads/trusted", "profiles": ["backend"],
                      "python": "python", "node": "node", "javaHome": "java", "androidHome": "sdk"}
            receipt = {"runId": "bounded", "state": "success"}
            with patch.object(watch, "next_commit", return_value="a" * 40), patch.object(ci, "run", return_value=receipt) as run:
                watch.tick(config, {})
                self.assertFalse(run.call_args.args[0].allow_degraded_volume)
                config["volumeException"] = {"authorized": True,
                    "expiresAtUtc": (now + timedelta(hours=1)).isoformat()}
                watch.tick(config, {})
                self.assertTrue(run.call_args.args[0].allow_degraded_volume)
                config["volumeException"]["expiresAtUtc"] = (now - timedelta(seconds=1)).isoformat()
                with self.assertRaises(ci.Refused):
                    watch.tick(config, {})
                self.assertEqual(run.call_count, 2)

    def test_remote_only_head_is_not_executed(self):
        with patch.object(ci, "git", return_value="a" * 40), patch.object(
                ci, "github", return_value={"commit": {"sha": "b" * 40}}), patch.object(ci, "validate_source") as validate:
            self.assertIsNone(watch.next_commit(Path.cwd(), "refs/heads/trusted"))
            validate.assert_not_called()

    def test_matching_remote_and_local_branch_is_revalidated(self):
        with patch.object(ci, "git", return_value="a" * 40), patch.object(
                ci, "github", return_value={"commit": {"sha": "a" * 40}}), patch.object(ci, "validate_source") as validate:
            self.assertEqual(watch.next_commit(Path.cwd(), "refs/heads/trusted"), "a" * 40)
            validate.assert_called_once()

    def test_pull_request_merge_ref_not_admitted(self):
        with self.assertRaises(ci.Refused):
            watch.next_commit(Path.cwd(), "refs/pull/19/merge")

    def test_failed_commit_is_not_repeated_on_every_poll(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(watch, "next_commit", return_value="a" * 40), patch.object(ci, "run") as run:
                state = watch.tick({"root": directory, "trustedRef": "refs/heads/trusted"},
                                   {"completedSha": "a" * 40, "lastRunState": "failure"})
            run.assert_not_called()
            self.assertEqual(state["lastRunState"], "failure")


if __name__ == "__main__":
    unittest.main()
