"""Finite, offline comparison of published DAG types and Android handlers.

This observes structural validation; it does not execute Kotlin/device actions,
use a database, send HTTP requests, or establish installed APK capabilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from backend.schemas.dag import VALID_ACTION_TYPES, DAGScript

ROOT = Path(__file__).resolve().parents[2]
FILES = ["backend/schemas/dag.py", "frontend/lib/dag/export.ts",
         "android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt",
         "android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output:
        target = args.output.resolve()
        if not target.is_relative_to(ROOT) or target.suffix != ".json":
            parser.error("Output must be a JSON file within this repository.")
    texts = [(ROOT / name).read_text(encoding="utf-8") for name in FILES]
    schema, frontend, android, _executor = texts
    del schema  # Parsed by Pydantic above, not reimplemented here.
    frontend_types = set(re.findall(r"'([a-z_]+)'", frontend.split("] as const;", 1)[0]))
    handler_block = android.split("private suspend fun executeNodeInternal(", 1)[1].split(
        "// ── Helpers", 1)[0]
    android_types = set(re.findall(r'^        "([a-z_]+)"\s*->', handler_block, flags=re.M))
    rows = []
    cases = {
        "tap_missing_coordinates": {"type": "tap"},
        "sleep_non_numeric_duration": {"type": "sleep", "ms": "not-a-number"},
        "set_variable_object_value": {"type": "set_variable", "key": "fixture", "value": {}},
        "condition_non_object_params": {"type": "condition", "check": "battery_above",
                                        "params": [], "on_true": "end", "on_false": "end"},
        "runtime_loop_not_published": {"type": "loop", "count": 1, "body": []},
    }
    for name, action in cases.items():
        dag = {"version": "1.0", "entry_node": "step", "nodes": [
            {"id": "step", "action": action, "on_success": "end"},
            {"id": "end", "action": {"type": "end"}},
        ]}
        try:
            DAGScript.model_validate(dag)
            rows.append({"name": name, "structuralValidationAccepted": True})
        except ValidationError as error:
            rows.append({"name": name, "structuralValidationAccepted": False,
                         "errors": [{"loc": list(e["loc"]), "type": e["type"]}
                                    for e in error.errors(include_input=False, include_context=False)]})
    result = {
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "checkoutCommit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "offline-structural-validation-and-source-inventory",
        "sourceHashes": {name: hashlib.sha256(text.encode()).hexdigest()
                         for name, text in zip(FILES, texts, strict=True)},
        "backendTypes": sorted(VALID_ACTION_TYPES), "frontendTypes": sorted(frontend_types),
        "androidHandlerTypes": sorted(android_types),
        "backendFrontendTypesEqual": set(VALID_ACTION_TYPES) == frontend_types,
        "runtimeOnlyTypes": sorted(android_types - VALID_ACTION_TYPES),
        "publishedTypesWithoutHandler": sorted(VALID_ACTION_TYPES - android_types),
        "cases": rows,
        "deviceExecutionVerified": False, "installedApkCapabilitiesVerified": False,
        "networkRequestsSent": False, "databaseUsed": False, "deviceCommandsSent": False,
    }
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
