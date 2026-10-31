"""Isolated PR-advisory tests: no GitHub requests, services or credentials."""

import html
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.documentation_pr_advisory import AdvisoryIncomplete, collect, main, parse_files, render

HEAD = "a" * 40
BASE = "b" * 40


def metadata(count, head=HEAD, base=BASE):
    return {"head": {"sha": head}, "base": {"sha": base}, "changed_files": count}


def fetch_sequence(responses):
    calls = []
    def fetch(path):
        calls.append(path)
        if not responses:
            raise AssertionError("Unexpected API request")
        expected, data = responses.pop(0)
        if path != expected:
            raise AssertionError(f"Expected {expected}, got {path}")
        return data
    return fetch, calls


class PullRequestAdvisoryTests(unittest.TestCase):
    def test_preserves_both_rename_paths_and_suggests_both_areas(self):
        files = [{"status": "renamed", "filename": "backend/api/v1/tasks/router.py",
                  "previous_filename": "frontend/app/(dashboard)/tasks/page.tsx"}]
        fetch, calls = fetch_sequence([( "", metadata(1)), ("/files?per_page=100&page=1", files), ("", metadata(1))])
        result = collect(fetch, HEAD, BASE, HEAD)
        self.assertEqual(set(result["changedPaths"]), {files[0]["filename"], files[0]["previous_filename"]})
        self.assertIn("HTTP API and schemas", [area["area"] for area in result["areas"]])
        self.assertEqual(len(calls), 3)

    def test_paginates_and_verifies_metadata_on_both_sides(self):
        first = [{"status": "modified", "filename": f"src/file-{i}"} for i in range(100)]
        last = [{"status": "added", "filename": "src/last"}]
        fetch, _ = fetch_sequence([( "", metadata(101)), ("/files?per_page=100&page=1", first),
                                   ("/files?per_page=100&page=2", last), ("", metadata(101))])
        self.assertEqual(len(collect(fetch, HEAD, BASE, HEAD)["changedPaths"]), 101)

    def test_rejects_stale_checkout_before_fetching_files(self):
        fetch, calls = fetch_sequence([( "", metadata(1))])
        with self.assertRaises(AdvisoryIncomplete):
            collect(fetch, HEAD, BASE, "c" * 40)
        self.assertEqual(calls, [""])

    def test_rejects_head_base_or_count_changed_after_pagination(self):
        file = [{"status": "modified", "filename": "README.md"}]
        for changed in (metadata(1, head="c" * 40), metadata(1, base="d" * 40), metadata(2)):
            with self.subTest(changed=changed):
                fetch, _ = fetch_sequence([( "", metadata(1)), ("/files?per_page=100&page=1", file), ("", changed)])
                with self.assertRaises(AdvisoryIncomplete):
                    collect(fetch, HEAD, BASE, HEAD)

    def test_rejects_incomplete_or_duplicate_pages_and_limit(self):
        cases = [
            [("", metadata(2)), ("/files?per_page=100&page=1", [{"status": "added", "filename": "a"}]), ("", metadata(2))],
            [("", metadata(2)), ("/files?per_page=100&page=1", [{"status": "added", "filename": "a"}, {"status": "added", "filename": "a"}])],
            [("", metadata(3000))],
        ]
        for responses in cases:
            with self.subTest(responses=responses):
                fetch, _ = fetch_sequence(responses.copy())
                with self.assertRaises(AdvisoryIncomplete):
                    collect(fetch, HEAD, BASE, HEAD)

    def test_rejects_malformed_rename_and_metadata(self):
        for entry in ([{"status": "renamed", "filename": "a"}], [{"status": "unknown", "filename": "b"}],
                      [{"status": "added", "filename": "bad\0name"}], [{"filename": "b"}]):
            with self.subTest(entry=entry), self.assertRaises(AdvisoryIncomplete):
                parse_files(entry)
        fetch, _ = fetch_sequence([( "", metadata(True))])
        with self.assertRaises(AdvisoryIncomplete):
            collect(fetch, HEAD, BASE, HEAD)

    def test_untrusted_path_cannot_inject_summary_markdown_or_html(self):
        name = 'backend/api/x\n</code><script>alert("x")</script>\n# forged [link](https://example.com)'
        fetch, _ = fetch_sequence([( "", metadata(1)), ("/files?per_page=100&page=1", [{"status": "added", "filename": name}]), ("", metadata(1))])
        summary = render(collect(fetch, HEAD, BASE, HEAD))
        self.assertNotIn("<script>", summary)
        self.assertNotIn("\n# forged", summary)
        self.assertNotIn("[link](https://example.com)", summary)
        self.assertIn('<script>alert', html.unescape(summary))
        self.assertIn(r"\n", html.unescape(summary))

    def test_summary_is_bounded_with_many_long_non_ascii_paths(self):
        first = [{"status": "added", "filename": "backend/api/" + "😀" * 500 + str(i)} for i in range(100)]
        fetch, _ = fetch_sequence([( "", metadata(100)), ("/files?per_page=100&page=1", first),
                                   ("/files?per_page=100&page=2", []), ("", metadata(100))])
        summary = render(collect(fetch, HEAD, BASE, HEAD))
        self.assertLess(len(summary.encode("utf-8")), 1_000_000)
        self.assertIn("Список путей в выводе ограничен", summary)

    def test_api_failure_is_incomplete_never_no_impact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            event = root / "event.json"
            summary = root / "summary"
            event.write_text(json.dumps({"number": 1, "pull_request": {"head": {"sha": HEAD}, "base": {"sha": BASE}}}), encoding="utf-8")
            env = {"GITHUB_EVENT_PATH": str(event), "PR_CHECKOUT_PATH": str(root), "TRUSTED_BASE_PATH": str(root),
                   "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "owner/repo",
                   "GITHUB_TOKEN": "not-a-real-token", "GITHUB_STEP_SUMMARY": str(summary)}
            with patch.dict("os.environ", env, clear=True), patch("scripts.documentation_pr_advisory.subprocess.run") as git, \
                    patch("scripts.documentation_pr_advisory.fetcher", side_effect=AdvisoryIncomplete("GitHub API unavailable")):
                git.side_effect = [SimpleNamespace(stdout=BASE), SimpleNamespace(stdout=HEAD)]
                self.assertEqual(main(), 0)
            contents = summary.read_text(encoding="utf-8")
            self.assertIn("неполный результат", contents)
            self.assertIn("невозможен", contents)
            self.assertNotIn("not-a-real-token", contents)

    def test_untrusted_or_missing_base_prevents_api_and_reports_incomplete(self):
        for base_result in (SimpleNamespace(stdout="c" * 40),
                            subprocess.CalledProcessError(1, "git", stderr="not-a-real-token")):
            with self.subTest(base_result=base_result), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                event = root / "event.json"
                summary = root / "summary"
                event.write_text(json.dumps({"number": 1, "pull_request": {"head": {"sha": HEAD}, "base": {"sha": BASE}}}), encoding="utf-8")
                env = {"GITHUB_EVENT_PATH": str(event), "PR_CHECKOUT_PATH": str(root), "TRUSTED_BASE_PATH": str(root),
                       "GITHUB_API_URL": "https://api.github.com", "GITHUB_REPOSITORY": "owner/repo",
                       "GITHUB_TOKEN": "not-a-real-token", "GITHUB_STEP_SUMMARY": str(summary)}
                with patch.dict("os.environ", env, clear=True), patch("scripts.documentation_pr_advisory.subprocess.run", side_effect=[base_result]), \
                        patch("scripts.documentation_pr_advisory.fetcher") as fetch:
                    self.assertEqual(main(), 0)
                    fetch.assert_not_called()
                contents = summary.read_text(encoding="utf-8")
                self.assertIn("неполный результат", contents)
                self.assertIn("общем предке", contents)
                self.assertIn("--base <база>", contents)
                self.assertNotIn("not-a-real-token", contents)


if __name__ == "__main__":
    unittest.main()
