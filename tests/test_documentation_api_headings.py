"""Check HTTP endpoint headings against the committed generated OpenAPI snapshot.

This is a bounded navigation check: it does not validate prose, payloads, auth,
WebSockets, runtime behavior or whether the committed schema is fresh.
"""
import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
HEADING = re.compile(r"^#{2,4}[ \t]+`?(GET|POST|PUT|PATCH|DELETE)[ \t]+`?([^\s`]+)", re.MULTILINE)


def canonical_path(path: str) -> str:
    """Normalize query, trailing slash and parameter names for endpoint matching."""
    path = urlsplit(path).path.rstrip("/")
    path = re.sub(r"\{[^/{}]+\}", "{}", path)
    return path if path.startswith("/api/v1/") else "/api/v1" + path


def missing_headings(text: str, schema: dict) -> list[str]:
    endpoints = {(method.upper(), canonical_path(path))
                 for path, operations in schema["paths"].items()
                 for method in operations if method.lower() in HTTP_METHODS}
    return [f"{method} {path}" for method, path in HEADING.findall(text)
            if (method, canonical_path(path)) not in endpoints]


class ApiHeadingTests(unittest.TestCase):
    def test_reference_http_headings_exist_in_openapi(self):
        schema = json.loads((ROOT / "docs/openapi.json").read_text(encoding="utf-8"))
        guide = (ROOT / "docs/api-reference.md").read_text(encoding="utf-8")
        self.assertIsNotNone(HEADING.search(guide), "No HTTP headings found in the reference")
        self.assertEqual(missing_headings(guide, schema), [])

    def test_method_path_and_query_are_checked(self):
        schema = {"paths": {"/api/v1/devices/{device_id}": {"get": {}}}}
        guide = "### `GET /devices/{id}?view=detail`\n### DELETE /devices/{id}\n"
        self.assertEqual(missing_headings(guide, schema), ["DELETE /devices/{id}"])


if __name__ == "__main__":
    unittest.main()
