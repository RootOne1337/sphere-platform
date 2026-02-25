#!/usr/bin/env python3
"""
scripts/check_rls.py
CI-инструмент: проверяет, что все таблицы с полем org_id покрыты
RLS-политиками в infrastructure/postgres/rls_policies.sql.

Завершается с exit code 1 если найдены непокрытые таблицы.

Использование:
    python scripts/check_rls.py
    python scripts/check_rls.py --rls-file infrastructure/postgres/rls_policies.sql

Используется в GitHub Actions job `rls-check` (ci-backend.yml).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


# Таблицы из models/__init__.py с полем org_id
# Поддерживается автоопределение через importlib, но для CI без asyncpg
# используется статичный список (обновляй при добавлении новых моделей с org_id)
TABLES_WITH_ORG_ID = {
    "organizations",   # RLS через slug/id (самоссылка — нет org_id FK, но есть политика)
    "users",
    "api_keys",
    "refresh_tokens",
    "audit_logs",
    "workstations",
    "device_groups",
    "devices",
    "ldplayer_instances",
    "scripts",
    "script_versions",
    "task_batches",
    "tasks",
    "vpn_peers",
    "webhooks",
}

# Таблицы-исключения (M2M без org_id — RLS через FK каскад)
EXEMPT_TABLES = {
    "device_group_members",  # RLS через devices и device_groups
    "alembic_version",
}


def extract_covered_tables(rls_sql: str) -> set[str]:
    """Извлекает имена таблиц, для которых создаются политики в rls_policies.sql."""
    # Паттерн: CREATE POLICY ... ON table_name ...
    pattern = re.compile(
        r"CREATE\s+POLICY\s+\w+\s+ON\s+(\w+)",
        re.IGNORECASE,
    )
    covered = set()
    for match in pattern.finditer(rls_sql):
        covered.add(match.group(1).lower())
    return covered


def main() -> None:
    parser = argparse.ArgumentParser(description="Check RLS policy coverage")
    parser.add_argument(
        "--rls-file",
        default="infrastructure/postgres/rls_policies.sql",
        help="Path to rls_policies.sql",
    )
    parser.add_argument(
        "--audit-rls-file",
        default="infrastructure/postgres/audit_log_policies.sql",
        help="Path to audit_log_policies.sql",
    )
    args = parser.parse_args()

    rls_path = Path(args.rls_file)
    audit_path = Path(args.audit_rls_file)

    if not rls_path.exists():
        print(f"ERROR: RLS file not found: {rls_path}", file=sys.stderr)
        sys.exit(1)

    rls_sql = rls_path.read_text(encoding="utf-8")
    if audit_path.exists():
        rls_sql += "\n" + audit_path.read_text(encoding="utf-8")

    covered = extract_covered_tables(rls_sql)
    required = TABLES_WITH_ORG_ID - EXEMPT_TABLES
    missing = required - covered

    print(f"✓ Tables with RLS policies: {len(covered)}")
    print(f"✓ Tables requiring coverage: {len(required)}")

    if missing:
        print("\n❌ MISSING RLS POLICIES for tables:", file=sys.stderr)
        for table in sorted(missing):
            print(f"   - {table}", file=sys.stderr)
        print(
            "\nAdd CREATE POLICY statements to rls_policies.sql for each missing table.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("\n✅ All tables are covered by RLS policies.")
    sys.exit(0)


if __name__ == "__main__":
    main()
