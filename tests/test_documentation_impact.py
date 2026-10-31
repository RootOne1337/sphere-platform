"""Behaviour tests for documentation impact suggestions and Git selection."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.documentation_impact import analyze, changed_paths, paths_from_name_status


class ImpactRulesTests(unittest.TestCase):
    def test_overlapping_rules_and_unknown_paths_remain_visible(self):
        result = analyze(["backend/api/v1/devices/router.py", "frontend/app/(dashboard)/devices/page.tsx", "misc/new.bin"])
        areas = {group["area"]: group for group in result["areas"]}
        self.assertIn("backend/api/v1/devices/router.py", areas["HTTP API and schemas"]["matchedPaths"])
        self.assertIn("frontend/app/(dashboard)/devices/page.tsx", areas["Web interface"]["matchedPaths"])
        self.assertIn("docs/operations/DEVICE-CATALOG.md", areas["Device and fleet"]["reviewCandidates"])
        self.assertEqual(result["unmappedPaths"], ["misc/new.bin"])

    def test_generic_api_router_does_not_trigger_route_studio(self):
        result = analyze(["backend/api/v1/users/router.py"])
        self.assertNotIn("Script and route studio", [group["area"] for group in result["areas"]])

    def test_git_rename_includes_old_and_new_names_and_spaces(self):
        data = b"R100\0frontend/app/old name.tsx\0backend/api/v1/new name.py\0M\0README.md\0"
        self.assertEqual(paths_from_name_status(data), ["frontend/app/old name.tsx", "backend/api/v1/new name.py", "README.md"])
        with self.assertRaises(ValueError):
            paths_from_name_status(b"R100\0old\0")


class GitSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Test")
        self.run_git("config", "user.email", "test@example.invalid")
        (self.root / "before.txt").write_text("content\n", encoding="utf-8")
        self.run_git("add", "before.txt")
        self.run_git("commit", "-qm", "baseline")
        self.baseline = self.run_git("rev-parse", "HEAD").strip()
        self.patch = patch("scripts.documentation_impact.ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def test_staged_worktree_and_branch_selections(self):
        self.run_git("mv", "before.txt", "after.txt")
        (self.root / "new file.txt").write_text("untracked", encoding="utf-8")
        (self.root / "ignored.txt").write_text("ignored", encoding="utf-8")
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        self.assertEqual(changed_paths("staged"), ["after.txt", "before.txt"])
        self.assertEqual(changed_paths("worktree"), [".gitignore", "after.txt", "before.txt", "new file.txt"])
        self.assertEqual(changed_paths("base", self.baseline), [])
        self.run_git("commit", "-qm", "rename")
        self.assertEqual(changed_paths("base", self.baseline), ["after.txt", "before.txt"])

    def test_ref_that_looks_like_an_option_is_rejected(self):
        with self.assertRaises(ValueError):
            changed_paths("base", "--help")


if __name__ == "__main__":
    unittest.main()
