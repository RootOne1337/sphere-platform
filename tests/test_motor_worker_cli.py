"""The route CLI must remain read-only, bounded and free of printed credentials."""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from motor_worker.__main__ import main

DEVICE = "753fd530-2f19-4e5e-98ba-769863678141"
VISION = all(importlib.util.find_spec(name) for name in ("cv2", "numpy"))


class MotorCliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.profile = self.root / "profile.json"
        source = Path(__file__).resolve().parents[1] / "examples/motor-minimap-profile.json"
        self.profile.write_bytes(source.read_bytes())
        self.output = self.root / "output.json"
        self.report = {
            "success": True,
            "control": {"requested": False},
            "route": {"path": "direct"},
        }
        self.session = SimpleNamespace(
            run=AsyncMock(return_value=self.report),
            frames=SimpleNamespace(latest=None, clear=Mock()),
            binding=None,
        )

    def invoke(self, extra):
        argv = [
            "motor_worker",
            "--base-url",
            "http://127.0.0.1:3015",
            "--device",
            DEVICE,
            "--output",
            str(self.output),
            *extra,
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", argv),
            patch.dict(os.environ, {"SPHERE_ACCESS_TOKEN": "fixture-private-token"}),
            patch("motor_worker.__main__.HeadlessSession", return_value=self.session) as factory,
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            result = main()
        self.assertNotIn("fixture-private-token", stdout.getvalue() + stderr.getvalue())
        return result, factory, stderr.getvalue()

    @unittest.skipUnless(VISION, "optional motor vision required")
    def test_minimap_mode_builds_read_only_session_and_closes_observer(self):
        code, factory, errors = self.invoke(
            ["--shadow-policy", "minimap", "--minimap-profile", str(self.profile)]
        )
        self.assertEqual(code, 0, errors)
        config = factory.call_args.args[0]
        observer = factory.call_args.kwargs["policy"]
        self.assertTrue(config.shadow_policy)
        self.assertFalse(config.probe_control)
        self.assertTrue(observer.closed)
        self.assertTrue(observer.report()["backgroundJobRetired"])
        self.assertEqual(json.loads(self.output.read_text())["control"], {"requested": False})

    def test_neutral_fixture_remains_available_without_route_profile(self):
        code, factory, _ = self.invoke(["--shadow-policy", "neutral"])
        self.assertEqual(code, 0)
        self.assertIsNone(factory.call_args.kwargs["policy"])
        self.assertTrue(factory.call_args.args[0].shadow_policy)

    def test_route_options_cannot_silently_enable_control_or_use_another_mode(self):
        invalid = [
            ["--shadow-policy", "minimap"],
            [
                "--shadow-policy",
                "minimap",
                "--minimap-profile",
                str(self.profile),
                "--probe-control",
            ],
            [
                "--shadow-policy",
                "minimap",
                "--minimap-profile",
                str(self.profile),
                "--pointer-probe",
                "anything",
            ],
            ["--shadow-policy", "neutral", "--minimap-profile", str(self.profile)],
            ["--goal-revision", DEVICE],
        ]
        for options in invalid:
            with self.subTest(options=options):
                code, factory, errors = self.invoke(options)
                self.assertEqual(code, 2)
                self.assertIn("invalid_minimap_shadow_options", errors)
                factory.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_missing_vision_dependencies_fail_before_device_contact(self):
        with patch("motor_worker.__main__.importlib.util.find_spec", return_value=None):
            code, factory, errors = self.invoke(
                ["--shadow-policy", "minimap", "--minimap-profile", str(self.profile)]
            )
        self.assertEqual(code, 2)
        self.assertIn("motor_vision_dependencies_missing", errors)
        factory.assert_not_called()

    @unittest.skipUnless(VISION, "optional motor vision required")
    def test_invalid_profile_and_goal_never_contact_device(self):
        self.profile.write_text(" " * 4097, encoding="utf-8")
        code, factory, _ = self.invoke(
            ["--shadow-policy", "minimap", "--minimap-profile", str(self.profile)]
        )
        self.assertEqual(code, 2)
        factory.assert_not_called()
        source = Path(__file__).resolve().parents[1] / "examples/motor-minimap-profile.json"
        self.profile.write_bytes(source.read_bytes())
        code, factory, _ = self.invoke(
            [
                "--shadow-policy",
                "minimap",
                "--minimap-profile",
                str(self.profile),
                "--goal-revision",
                "bad",
            ]
        )
        self.assertEqual(code, 2)
        factory.assert_not_called()

    @unittest.skipUnless(VISION, "optional motor vision required")
    def test_model_import_failure_still_closes_route_observer_and_reports_fixed_error(self):
        self.session.run.side_effect = ImportError("private path not for diagnostics")
        code, factory, _ = self.invoke(
            ["--shadow-policy", "minimap", "--minimap-profile", str(self.profile)]
        )
        self.assertEqual(code, 1)
        self.assertTrue(factory.call_args.kwargs["policy"].closed)
        self.assertEqual(
            json.loads(self.output.read_text())["failure"], "motor_dependencies_missing"
        )

    @unittest.skipUnless(VISION, "optional motor vision required")
    def test_existing_output_is_preserved_before_session_creation(self):
        self.output.write_text("keep original", encoding="utf-8")
        code, factory, _ = self.invoke(
            ["--shadow-policy", "minimap", "--minimap-profile", str(self.profile)]
        )
        self.assertEqual(code, 2)
        factory.assert_not_called()
        self.assertEqual(self.output.read_text(), "keep original")
