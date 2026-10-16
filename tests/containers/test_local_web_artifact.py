"""Local image acceptance must not invent hosted CI, browser readiness or successful tests."""

import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.pilot import install_reviewed_web as installer
from scripts.pilot import local_web_artifact as local

SOURCE = "a" * 40
IMAGE = "sha256:" + "b" * 64
RUN = "20261016T022900Z-01234567"
DIGEST = "c" * 64


def image():
    return dict(
        Id=IMAGE,
        Os="linux",
        Architecture="amd64",
        Config=dict(
            User="1001:1001",
            Cmd=["node", "server.js"],
            WorkingDir="/app",
            Entrypoint=["docker-entrypoint.sh"],
            Labels={
                "org.opencontainers.image.revision": SOURCE,
                "io.sphere.local.run": RUN,
                "io.sphere.local.source": DIGEST,
            },
        ),
    )


def probe():
    return dict(
        imageId=IMAGE,
        loopbackOnly=True,
        readOnlyContainer=True,
        ownedContainerRemoved=True,
        browserHydrationVerified=False,
        backendExecutionVerified=False,
        clientAssetsVerified=16,
        pages=[
            dict(route=route, status=200, **(dict(redirect="next-flight") if route == "/" else {}))
            for route in sorted(local.REQUIRED_ROUTES)
        ],
    )


def execution():
    return dict(
        schemaVersion=1,
        runId=RUN,
        state="success",
        workflowMode="maintainer-local-executor",
        publicForkJobsAccepted=False,
        source=dict(sha=SOURCE, repository="RootOne1337/sphere-platform"),
        profiles=dict(
            frontend=dict(
                state="success",
                startedAt="2026-10-16T02:29:00+00:00",
                tests=dict(
                    tests=10,
                    passed=10,
                    failures=0,
                    failedSuites=0,
                    skipped=0,
                    suites=2,
                    success=True,
                ),
                steps=[
                    dict(name=name, exitCode=0, timedOut=False)
                    for name in [
                        "action-contract",
                        "jest",
                        "test_preview_relay.cjs",
                        "test_frontend_standalone_probe.mjs",
                        "test_package_command_failure.mjs",
                        "archive-admission",
                        "types",
                    ]
                ],
                github=dict(
                    context="Sphere Local / Frontend regressions",
                    state="success",
                    readbackVerified=True,
                    id=123,
                ),
            )
        ),
    )


class LocalWebTests(unittest.TestCase):
    def test_runtime_requires_exact_unprivileged_image_source_and_platform(self):
        local.validate_image(image(), SOURCE, RUN, DIGEST, IMAGE)
        for key, value in [
            ("Id", "sha256:" + "d" * 64),
            ("Os", "windows"),
            ("Architecture", "arm64"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                local.validate_image(image() | {key: value}, SOURCE, RUN, DIGEST, IMAGE)
        for key, value in [
            ("User", "root"),
            ("Cmd", ["sh"]),
            ("Volumes", {"/app": {}}),
            ("Labels", None),
        ]:
            bad = image()
            bad["Config"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                local.validate_image(bad, SOURCE, RUN, DIGEST, IMAGE)
        for key in [
            "org.opencontainers.image.revision",
            "io.sphere.local.run",
            "io.sphere.local.source",
        ]:
            bad = image()
            bad["Config"]["Labels"][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                local.validate_image(bad, SOURCE, RUN, DIGEST, IMAGE)

    def test_http_probe_is_scoped_and_requires_all_core_pages(self):
        local.validate_probe(probe(), IMAGE)
        for key, value in [
            ("imageId", "wrong"),
            ("loopbackOnly", False),
            ("readOnlyContainer", False),
            ("ownedContainerRemoved", False),
            ("browserHydrationVerified", True),
            ("backendExecutionVerified", True),
            ("clientAssetsVerified", 0),
            ("clientAssetsVerified", True),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                local.validate_probe(probe() | {key: value}, IMAGE)
        for pages in [[], probe()["pages"][:-1], [*probe()["pages"], probe()["pages"][0]], [None]]:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                local.validate_probe(probe() | dict(pages=pages), IMAGE)
        for route in ["/", "/devices"]:
            bad = probe()
            next(row for row in bad["pages"] if row["route"] == route)["status"] = 500
            with self.subTest(route=route), self.assertRaises(ValueError):
                local.validate_probe(bad, IMAGE)

    def run_admission(self, data, *, original_tests=None, remote_id=123):
        item = dict(file=f"local-ci/runs/{RUN}/receipt.json", sha256="f" * 64)
        with (
            patch.object(local, "hashed_evidence", return_value=data),
            patch.object(local, "private_file", return_value=Path("jest.json")),
            patch.object(
                local,
                "jest_counts",
                return_value=original_tests or data["profiles"]["frontend"]["tests"],
            ),
            patch.object(
                local,
                "command",
                return_value=json.dumps(
                    [
                        dict(
                            context="Sphere Local / Frontend regressions",
                            id=remote_id,
                            state="success",
                        )
                    ]
                ),
            ),
        ):
            return local.frontend_run(item, SOURCE)

    def test_full_local_test_counts_and_exact_github_readback_are_required(self):
        self.assertEqual(self.run_admission(execution()), RUN)
        with self.assertRaises(ValueError):
            self.run_admission(execution(), remote_id=999)
        with self.assertRaises(ValueError):
            self.run_admission(execution(), original_tests=dict(tests=99))

    def test_failure_missing_steps_and_hosted_fork_spoof_are_refused(self):
        for mutation in [
            lambda x: x.update(workflowMode="github-actions"),
            lambda x: x.update(publicForkJobsAccepted=True),
            lambda x: x["source"].update(sha="d" * 40),
            lambda x: x["profiles"]["frontend"].update(state="failure"),
            lambda x: x["profiles"]["frontend"]["tests"].update(failures=1),
            lambda x: x["profiles"]["frontend"]["steps"].pop(),
            lambda x: x["profiles"]["frontend"]["steps"][0].update(timedOut=True),
            lambda x: x["profiles"]["frontend"]["github"].update(readbackVerified=False),
        ]:
            bad = copy.deepcopy(execution())
            mutation(bad)
            with self.subTest(data=bad), self.assertRaises(ValueError):
                self.run_admission(bad)

    def test_explicit_local_mode_never_uses_hosted_admission(self):
        with (
            patch.object(local, "admit_local", return_value=dict(imageId=IMAGE)) as admitted,
            patch.object(installer, "admit") as hosted,
        ):
            self.assertEqual(
                installer.admit_candidate(Path("candidate"), SOURCE, True), dict(imageId=IMAGE)
            )
            admitted.assert_called_once_with(Path("candidate"), SOURCE)
            hosted.assert_not_called()

    def test_hosted_mode_remains_default_and_does_not_accept_local_receipt(self):
        with (
            patch.object(local, "admit_local") as admitted,
            patch.object(installer, "admit", return_value=dict(imageId=IMAGE)) as hosted,
        ):
            self.assertEqual(
                installer.admit_candidate(Path("candidate"), SOURCE, False), dict(imageId=IMAGE)
            )
            hosted.assert_called_once_with(Path("candidate"), SOURCE)
            admitted.assert_not_called()

    def test_receipt_source_hash_is_checked_before_image_admission(self):
        raw = b"canonical source"
        receipt = dict(
            schemaVersion=1,
            kind="sphere-local-web",
            sourceRevision=SOURCE,
            runtimeInstalled=False,
            repository="RootOne1337/sphere-platform",
            archivesCreated=0,
            localExecution={},
            sourceArchiveSha256=hashlib.sha256(raw + b"changed").hexdigest(),
        )
        with (
            patch.object(local, "validate_source"),
            patch.object(local, "private_file"),
            patch.object(local, "bounded_json", return_value=receipt),
            patch.object(local, "frontend_run", return_value=RUN),
            patch.object(local, "canonical_frontend", return_value=raw),
            patch.object(local, "command") as command,
        ):
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                local.admit_local(local.ROOT / ".local-pilot/candidate", SOURCE)
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
