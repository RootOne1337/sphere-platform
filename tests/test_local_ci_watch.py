"""Remote forks and unpushed source must not schedule local host executions."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import local_ci as ci
from scripts.pilot import local_ci_watch as watch


class LocalCIQueueTest(unittest.TestCase):
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
