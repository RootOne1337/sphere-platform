"""Original successful artifact jobs survive a partial rerun without provenance edits."""
import json
import unittest
from unittest.mock import Mock

from scripts.pilot.reviewed_ci import check_artifact_attempt


class ArtifactAttemptTests(unittest.TestCase):
    receipt = {"runId": 17, "runAttempt": 1, "sourceRevision": "a" * 40}

    def job(self):
        return {"name": "Production image bootstrap", "run_id": 17, "head_sha": "a" * 40,
                "run_attempt": 1, "status": "completed", "conclusion": "success"}

    def runner(self, jobs, count=None):
        return Mock(return_value=json.dumps({"jobs": jobs, "total_count": len(jobs) if count is None else count}))

    def test_same_attempt_does_not_fetch_unrelated_jobs(self):
        runner = Mock()
        check_artifact_attempt({"run_attempt": 1}, self.receipt, runner)
        runner.assert_not_called()

    def test_partial_rerun_keeps_original_successful_artifact_attempt(self):
        runner = self.runner([self.job()])
        check_artifact_attempt({"run_attempt": 2}, self.receipt, runner)
        self.assertEqual(self.receipt["runAttempt"], 1)
        self.assertIn("/attempts/1/jobs?per_page=100", runner.call_args.args[0][-1])

    def test_future_or_invalid_attempt_is_rejected(self):
        for latest in (0, -1, None, True, "2"):
            with self.subTest(latest=latest), self.assertRaises(ValueError):
                check_artifact_attempt({"run_attempt": latest}, self.receipt, Mock())
        with self.assertRaises(ValueError):
            check_artifact_attempt({"run_attempt": 1}, self.receipt | {"runAttempt": 2}, Mock())

    def test_job_identity_and_success_are_independent(self):
        for key, value in (("run_id", 18), ("head_sha", "b" * 40), ("run_attempt", 2),
                           ("status", "in_progress"), ("conclusion", "failure")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_artifact_attempt({"run_attempt": 2}, self.receipt, self.runner([self.job() | {key: value}]))

    def test_missing_duplicate_or_incomplete_original_job_inventory_is_rejected(self):
        for jobs, count in (([], 0), ([self.job(), self.job()], 2), ([self.job()], 2), ([None], 1)):
            with self.subTest(jobs=jobs, count=count), self.assertRaises(ValueError):
                check_artifact_attempt({"run_attempt": 2}, self.receipt, self.runner(jobs, count))


if __name__ == "__main__":
    unittest.main()
