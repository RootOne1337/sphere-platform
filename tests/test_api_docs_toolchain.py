"""Generated contracts must use the same schema libraries as the API image."""

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from scripts.export_api_docs import schema_toolchain_error


class SchemaToolchainTests(TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "backend").mkdir()
        (self.root / "backend/requirements.txt").write_text(
            "fastapi==0.136.3\npydantic==2.9.2\npydantic[email]==2.9.2\n",
            encoding="utf-8",
        )

    def test_accepts_the_shipped_schema_toolchain(self):
        with patch("scripts.export_api_docs.version", side_effect=["0.136.3", "2.9.2"]):
            self.assertIsNone(schema_toolchain_error(self.root))

    def test_rejects_newer_schema_generators_before_importing_the_application(self):
        with patch("scripts.export_api_docs.version", side_effect=["0.141.1", "2.13.5"]):
            error = schema_toolchain_error(self.root)
        self.assertIn("fastapi: expected 0.136.3, installed 0.141.1", error)
        self.assertIn("pydantic: expected 2.9.2, installed 2.13.5", error)

    def test_reports_missing_packages_and_unpinned_requirements(self):
        (self.root / "backend/requirements.txt").write_text(
            "fastapi>=0.136.3\npydantic==2.9.2\n", encoding="utf-8",
        )
        with patch("scripts.export_api_docs.version", side_effect=PackageNotFoundError):
            error = schema_toolchain_error(self.root)
        self.assertIn("fastapi: expected one exact backend requirement pin", error)
        self.assertIn("pydantic: expected 2.9.2, installed not installed", error)
