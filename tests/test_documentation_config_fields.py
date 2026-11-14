"""Check that backend Settings field names appear in the configuration reference.

Presence is not a semantic check of defaults, deployment or secrets; no env is loaded.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def settings_fields(source: str) -> set[str]:
    module = ast.parse(source)
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Settings")
    return {node.target.id for node in cls.body
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)}


class ConfigurationReferenceTests(unittest.TestCase):
    def test_settings_fields_are_named_in_reference(self):
        fields = settings_fields((ROOT / "backend/core/config.py").read_text(encoding="utf-8"))
        reference = (ROOT / "docs/configuration.md").read_text(encoding="utf-8")
        self.assertTrue(fields, "Settings has no fields to review")
        self.assertEqual(sorted(field for field in fields if f"`{field}`" not in reference), [])

    def test_collects_annotated_fields_without_importing_settings(self):
        self.assertEqual(settings_fields("class Settings:\n    API_KEY: str\n    TIMEOUT: int = 3\n    model_config = {}\n"), {"API_KEY", "TIMEOUT"})


if __name__ == "__main__":
    unittest.main()
