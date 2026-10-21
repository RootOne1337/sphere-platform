"""A resource interruption may resume a build, never recycle a probe or retag it."""

import copy
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import package_local_web as pack
from tests.containers.test_local_web_artifact import IMAGE, RUN, SOURCE, image


class ResumeBuildTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / ".local-pilot/candidate"
        self.output.mkdir(parents=True)
        self.paths = ["pack.py", "admit.py", "Dockerfile", "probe.mjs"]
        (self.root / "Dockerfile").write_bytes(b"original recipe")
        (self.root / "probe.mjs").write_bytes(b"original probe")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            entry = tarfile.TarInfo("frontend/app/page.tsx")
            entry.size = 8
            archive.addfile(entry, io.BytesIO(b"original"))
        self.raw = buffer.getvalue()
        context = self.output / "context/frontend/app"
        context.mkdir(parents=True)
        (context / "page.tsx").write_bytes(b"original")
        (self.output / "build.private.log").write_bytes(b"build succeeded")
        self.binding = dict(
            sourceRevision=SOURCE,
            sourceArchiveSha256=hashlib.sha256(self.raw).hexdigest(),
            runId=RUN,
            imageId=IMAGE,
            exitCode=0,
            toolingSource="d" * 40,
            dockerfileSha256=hashlib.sha256(b"original recipe").hexdigest(),
        )
        self.candidate = image()
        self.candidate["Config"]["Labels"]["io.sphere.local.source"] = self.binding[
            "sourceArchiveSha256"
        ]
        for target, value in [(pack, self.root), (pack.installer, self.root)]:
            p = patch.object(target, "ROOT", value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(pack.installer, "PRIVATE", self.root / ".local-pilot")
        p.start()
        self.addCleanup(p.stop)

    def resume(self, *, recipe_changed=False):
        (self.output / "build-binding.json").write_text(json.dumps(self.binding), encoding="utf-8")
        self.calls = []

        def command(args):
            self.calls.append(args)
            if args[:2] == ["git", "diff"]:
                return "changed" if recipe_changed else ""
            if args[:3] == ["docker", "image", "inspect"]:
                return json.dumps([self.candidate])
            self.fail(f"Unexpected command: {args}")

        with (
            patch.object(pack, "validate_source") as trusted,
            patch.object(pack, "command", side_effect=command),
        ):
            result = pack.resume_build(self.output, SOURCE, RUN, self.raw, self.paths)
            trusted.assert_called_once_with(
                self.root, "d" * 40, "refs/heads/codex/enterprise-audit-20260905"
            )
            return result

    def test_intact_build_uses_exact_existing_image_without_build_or_retag(self):
        self.assertEqual(self.resume()["Id"], IMAGE)
        self.assertEqual(
            self.calls[-1], ["docker", "image", "inspect", f"sphere-review-frontend:{SOURCE}"]
        )
        self.assertEqual(len(self.calls), 3)

    def test_probe_receipt_partial_probe_and_unknown_files_are_refused(self):
        for name in ["receipt.json", "http-probe.json", "probe.private.log", "unexpected"]:
            with self.subTest(name=name):
                extra = self.output / name
                extra.write_bytes(b"anything")
                with self.assertRaisesRegex(ValueError, "unprobed"):
                    self.resume()
                extra.unlink()

    def test_source_execution_failure_and_image_bindings_are_required(self):
        original = copy.deepcopy(self.binding)
        for field, value in [
            ("sourceRevision", "f" * 40),
            ("sourceArchiveSha256", "f" * 64),
            ("runId", "another run"),
            ("exitCode", 1),
            ("exitCode", False),
            ("dockerfileSha256", "f" * 64),
            ("imageId", "sha256:" + "f" * 64),
        ]:
            self.binding = original | {field: value}
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.resume()
        self.binding = original

    def test_changed_missing_and_extra_context_files_are_refused(self):
        page = self.output / "context/frontend/app/page.tsx"
        page.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "context changed"):
            self.resume()
        page.unlink()
        with self.assertRaisesRegex(ValueError, "context changed"):
            self.resume()
        page.write_bytes(b"original")
        (page.parent / "secret.env").write_bytes(b"unexpected")
        with self.assertRaisesRegex(ValueError, "context changed"):
            self.resume()

    def test_changed_original_recipe_or_probe_cannot_borrow_build(self):
        with self.assertRaisesRegex(ValueError, "recipe or HTTP probe changed"):
            self.resume(recipe_changed=True)

    def test_changed_platform_runtime_and_labels_are_refused(self):
        original = copy.deepcopy(self.candidate)
        for mutation in [
            lambda x: x.update(Architecture="arm64"),
            lambda x: x["Config"].update(User="root"),
            lambda x: x["Config"]["Labels"].update({"io.sphere.local.run": "wrong"}),
        ]:
            self.candidate = copy.deepcopy(original)
            mutation(self.candidate)
            with self.subTest(candidate=self.candidate), self.assertRaises(ValueError):
                self.resume()

    def test_resume_still_stops_at_resource_guard_before_inspection_or_probe(self):
        node = self.root / "node.exe"
        node.touch()
        with (
            patch.object(pack, "validate_source"),
            patch.object(pack, "evidence"),
            patch.object(pack, "frontend_run", return_value=RUN),
            patch.object(
                pack,
                "command",
                side_effect=["v24.19.0", SOURCE, "blob", "blob", "blob", "blob", ""],
            ),
            patch.object(pack, "collect"),
            patch.object(pack, "evaluate", return_value=["commit_headroom_low"]),
            patch.object(pack, "resume_build") as resume,
            patch.object(pack.subprocess, "run") as probe,
        ):
            with self.assertRaisesRegex(ValueError, "Host resources not admitted"):
                pack.package(SOURCE, self.root / "execution", self.output, node, resume=True)
            resume.assert_not_called()
            probe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
