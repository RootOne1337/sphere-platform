#!/usr/bin/env python3
"""Compare the RLS migration inventory with model declarations (stdlib-only CI).

This detects omitted tables, including associations without org_id. It cannot
prove policy behavior: tests/production/test_rls_*.py execute the migrated schema
on PostgreSQL as separate non-owner roles.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/20260908_tenant_policies.py"


def model_tables(directory: Path) -> set[str]:
    tables = set()
    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            value = None
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "__tablename__" for target in node.targets
            ):
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "__tablename__":
                value = node.value
            elif isinstance(node, ast.Call) and (
                isinstance(node.func, ast.Name) and node.func.id == "Table"
                or isinstance(node.func, ast.Attribute) and node.func.attr == "Table"
            ):
                value = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "name"), None)
                if value is None:
                    raise ValueError(f"Cannot determine Table name: {path}:{node.lineno}")
            if value is not None:
                name = ast.literal_eval(value)
                if not isinstance(name, str):
                    raise ValueError(f"Non-string table name: {path}:{node.lineno}")
                tables.add(name)
    if not tables:
        raise ValueError("No model tables discovered")
    return tables


def migration_tables(path: Path) -> set[str]:
    values = {}
    for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"ORG_TABLES", "IDENTITY_TABLES", "ASSOCIATIONS"}:
                    values[target.id] = ast.literal_eval(node.value)
    if set(values) != {"ORG_TABLES", "IDENTITY_TABLES", "ASSOCIATIONS"}:
        raise ValueError("Migration must declare all three policy inventories")
    return set(values["ORG_TABLES"]) | set(values["IDENTITY_TABLES"]) | set(values["ASSOCIATIONS"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, default=ROOT / "backend/models")
    parser.add_argument("--migration", type=Path, default=MIGRATION)
    args = parser.parse_args()
    try:
        required = model_tables(args.models)
        covered = migration_tables(args.migration)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"RLS inventory check failed: {exc}")
        return 1
    missing, stale = required - covered, covered - required
    if missing or stale:
        print(f"Missing from migration: {sorted(missing)}; absent from models: {sorted(stale)}")
        print("Add a reviewed policy migration and update the inventory reference; associations are not exempt.")
        return 1
    print(f"RLS migration inventory matches all {len(required)} model tables (including associations).")
    print("Static inventory only. PostgreSQL runtime role/policy regressions are required separately.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
