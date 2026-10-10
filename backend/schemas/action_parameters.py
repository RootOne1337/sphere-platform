"""Pure, versioned parameter validation for new publications, never execution.

No coercion, defaults, source mutation, device calls or input values in errors.
Historical DAG structural parsing remains compatible and keeps original hashes.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

CONTRACT: dict[str, Any] = json.loads(Path(__file__).with_name("action_contract.v1.json").read_text(encoding="utf-8"))
ACTION_CONTRACT_VERSION: str = CONTRACT["version"]
MAX_ERRORS = 100


def action_parameter_errors(nodes: list[dict]) -> list[dict]:
    errors: list[dict] = []
    seen: set[tuple] = set()

    def fail(path: list[str | int], code: str) -> None:
        key = (*path, code)
        if len(errors) < MAX_ERRORS and key not in seen:
            seen.add(key)
            errors.append({"loc": path, "type": f"action_parameter.{code}", "msg": CONTRACT["messages"][code]})

    def visit(value: Any, raw_rule: dict, path: list[str | int], present: bool = True) -> None:
        if len(errors) >= MAX_ERRORS:
            return
        rule = {**CONTRACT["definitions"].get(raw_rule.get("ref"), {}), **raw_rule}
        if not present:
            if rule.get("required"):
                fail(path, "required")
            return
        kind: str = rule["type"]
        numeric = isinstance(value, (int, float)) and not isinstance(value, bool)
        finite = numeric and (isinstance(value, int) or math.isfinite(value))
        valid = {
            # Kotlin jsonPrimitive.int/long reject the spelling 1.0. Direct
            # API clients must send integer tokens; never silently coerce them.
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": finite,
            "boolean": isinstance(value, bool),
            "string": isinstance(value, str),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "primitive": value is None or isinstance(value, (str, bool)) or finite,
        }.get(kind, False)
        if not valid:
            fail(path, kind)
            return
        if kind in ("integer", "number"):
            if "min" in rule and value < rule["min"] or "max" in rule and value > rule["max"]:
                fail(path, "range")
        if kind in ("string", "array", "object"):
            if "min" in rule and len(value) < rule["min"] or "max" in rule and len(value) > rule["max"] or rule.get("nonblank") and not value.strip():
                fail(path, "length")
                return
        if "enum" in rule and (value.upper() if rule.get("case") == "upper" else value) not in rule["enum"]:
            fail(path, "enum")
        if rule.get("pattern") and re.fullmatch(rule["pattern"], value) is None:
            fail(path, "pattern")
        if rule.get("format") == "http_url":
            try:
                parts = urlsplit(value)
                valid_url = value.startswith(("http://", "https://")) and bool(parts.hostname) and not re.search(r"\s", value)
                _ = parts.port  # Reject invalid ports without network access.
            except ValueError:
                valid_url = False
            if not valid_url:
                fail(path, "http_url")
        if kind == "array" and "items" in rule:
            for index, item in enumerate(value):
                visit(item, rule["items"], [*path, index])
        if kind == "object":
            for key, child in rule.get("fields", {}).items():
                visit(value.get(key), child, [*path, key], key in value)
            if "values" in rule:
                for key, item in value.items():
                    # Header names can contain secrets too; don't reflect them.
                    child_path = [*path, "<entry>"]
                    if re.fullmatch(rule["key_pattern"], key) is None:
                        fail(child_path, "pattern")
                    visit(item, rule["values"], child_path)

    for index, node in enumerate(nodes):
        if len(errors) >= MAX_ERRORS:
            break
        action = node["action"]
        path: list[str | int] = ["nodes", index, "action"]
        spec = CONTRACT["actions"].get(action.get("type"))
        if spec is None:
            fail([*path, "type"], "type")
            continue
        visit(action, {"type": "object", "fields": {**CONTRACT["common_fields"], **spec["fields"]}}, path)
        checks = spec.get("checks")
        if checks:
            check = action.get("check")
            if isinstance(check, str) and check in checks:
                visit(action.get("params"), checks[check], [*path, "params"], "params" in action)
            elif not (spec.get("fallback_field") and isinstance(action.get(spec["fallback_field"]), str) and action[spec["fallback_field"]].strip()):
                fail([*path, "check"], "check")
    return errors
