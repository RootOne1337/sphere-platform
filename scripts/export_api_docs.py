"""Export the registered HTTP schema without starting the application lifespan.

Run from the repository root with backend dependencies/configuration available:
    python -m scripts.export_api_docs
    python -m scripts.export_api_docs --check

This describes declared HTTP contracts. It does not exercise authorization,
service availability, WebSocket protocols or device execution.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def render_catalog(schema: dict) -> str:
    rows = []
    for path, item in sorted(schema["paths"].items()):
        for method, operation in sorted(item.items()):
            if method not in METHODS:
                continue
            summary = " ".join(str(operation.get("summary", "")).split()).replace("|", "\\|")
            tags = ", ".join(operation.get("tags", [])) or "—"
            responses = ", ".join(sorted(operation.get("responses", {})))
            rows.append(f"| `{method.upper()}` | `{path}` | {tags} | {responses} | {summary} |")
    return "\n".join([
        "# Generated HTTP endpoint catalog", "",
        "Generated from `backend.main.app.openapi()` by `scripts/export_api_docs.py`.",
        "Regenerate with `python -m scripts.export_api_docs`; verify with `--check`.",
        "The exporter does not run startup hooks or send HTTP requests.", "",
        f"**{len(rows)} HTTP operations across {len(schema['paths'])} paths.**", "",
        "Full parameters, request bodies, response schemas and declared security schemes:",
        "[OpenAPI JSON](openapi.json). Manual explanations:",
        "[API reference](api-reference.md), [task controls](security/task-control-protocol.md).", "",
        "Only declared HTTP operations are listed. OpenAPI omits WebSocket protocols,",
        "plain ASGI routes such as /metrics, and some runtime authorization/error behavior.",
        "A listed response does not prove runtime success or production readiness.",
        "See [Android guide](android-agent.md) and [audit report](audits/2026-09-05/AUDIT-REPORT.md)",
        "for tested behavior and remaining limits.", "",
        "| Method | Path | Tags | Declared responses | Summary |",
        "| --- | --- | --- | --- | --- |",
        *rows, "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed documents differ")
    args = parser.parse_args()

    from backend.main import app

    schema = app.openapi()
    root = Path(__file__).resolve().parents[1]
    outputs = {
        root / "docs/openapi.json": json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        root / "docs/api-endpoints.md": render_catalog(schema),
    }
    stale = []
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.relative_to(root).as_posix())
        else:
            path.write_text(content, encoding="utf-8")
            print(f"Updated {path.relative_to(root).as_posix()}")
    if stale:
        print("Stale API documentation: " + ", ".join(stale))
        return 1
    if args.check:
        print("API schema and endpoint catalog match the registered application.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
