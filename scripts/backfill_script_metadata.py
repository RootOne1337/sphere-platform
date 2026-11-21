"""Bounded, tenant-explicit metadata maintenance; dry-run unless --apply is given.

Writes only derived fields, preserves source/version/pointer/timestamps, never
creates tasks or invokes Android. Repeat from the reported cursor after a clean
run. Failed rows are counted and identified without logging their DAGs.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid

from sqlalchemy import Text, and_, cast, func, or_, select, text, update
from sqlalchemy.exc import DBAPIError

from backend.database.engine import AsyncSessionLocal
from backend.database.tenant import bind_tenant_context
from backend.models.script import Script, ScriptVersion
from backend.services.script_service import _compute_dag_metadata


async def _query_budget(db, remaining: float) -> None:
    # A stalled SQL call must not outlive the maintenance wall-clock budget.
    milliseconds = max(1, min(10000, int(remaining * 1000)))
    await db.execute(text("SELECT set_config('statement_timeout', :budget, true)"),
                     {"budget": str(milliseconds)})


async def metadata_readiness(sessions, *, org_id: uuid.UUID) -> dict:
    """Scalar-only completeness/ownership check; it does not certify source hashes."""
    async with sessions() as db:
        await bind_tenant_context(db, str(org_id))
        await _query_budget(db, 10)
        owned = and_(ScriptVersion.id == Script.current_version_id,
                     ScriptVersion.script_id == Script.id, ScriptVersion.org_id == Script.org_id)
        counters = select(
            func.count().label("scripts"),
            func.count().filter(Script.current_version_id.is_not(None), ScriptVersion.id.is_(None)).label("invalid_pointers"),
            func.count().filter(Script.current_version_id.is_not(None), ScriptVersion.id.is_not(None),
                                or_(ScriptVersion.dag_hash.is_(None), ScriptVersion.node_count.is_(None))).label("current_missing"),
        ).select_from(Script.__table__.outerjoin(ScriptVersion.__table__, owned)).where(Script.org_id == org_id)
        row = (await db.execute(counters)).one()
        missing = await db.scalar(select(func.count()).select_from(ScriptVersion).where(
            ScriptVersion.org_id == org_id, or_(ScriptVersion.dag_hash.is_(None), ScriptVersion.node_count.is_(None)),
        ))
    return {"org_id": str(org_id), "scripts": row.scripts, "invalid_current_pointers": row.invalid_pointers,
            "current_metadata_missing": row.current_missing, "version_metadata_missing": missing,
            "catalog_ready": row.invalid_pointers == 0 and row.current_missing == 0,
            "source_hashes_reconciled": False}


async def backfill(
    sessions, *, org_id: uuid.UUID, apply: bool = False, reconcile: bool = False,
    after: uuid.UUID | None = None, max_versions: int = 1000,
    max_seconds: float = 60, max_source_bytes: int = 8 * 1024 * 1024,
) -> dict:
    if not (1 <= max_versions <= 10000 and 0 < max_seconds <= 300
            and 1024 <= max_source_bytes <= 64 * 1024 * 1024):
        raise ValueError("Invalid bounded maintenance budget")
    start = time.monotonic()
    result = {"schema": 1, "org_id": str(org_id), "apply": apply, "reconcile": reconcile,
              "scanned": 0, "would_update": 0, "updated": 0, "failed": 0,
              "failures": [], "after": str(after) if after else None, "stopped": "complete",
              "source_changed": False, "tasks_created": 0}
    cursor = after
    while result["scanned"] < max_versions and time.monotonic() - start < max_seconds:
        try:
            async with sessions() as db:
                await bind_tenant_context(db, str(org_id))
                await _query_budget(db, max_seconds - (time.monotonic() - start))
                stmt = select(ScriptVersion.id).where(ScriptVersion.org_id == org_id)
                if cursor is not None:
                    stmt = stmt.where(ScriptVersion.id > cursor)
                if not reconcile:
                    stmt = stmt.where(or_(ScriptVersion.dag_hash.is_(None), ScriptVersion.node_count.is_(None)))
                ids = list(await db.scalars(stmt.order_by(ScriptVersion.id).limit(min(10, max_versions - result["scanned"]))))
        except DBAPIError as error:
            if getattr(error.orig, "sqlstate", None) != "57014":
                raise
            result["stopped"] = "query_budget"
            return result
        if not ids:
            break
        for version_id in ids:
            if time.monotonic() - start >= max_seconds:
                result["stopped"] = "time_budget"
                return result
            try:
                async with sessions() as db:
                    await bind_tenant_context(db, str(org_id))
                    await _query_budget(db, max_seconds - (time.monotonic() - start))
                    # Lock before measuring: concurrent legacy UPDATEs cannot
                    # enlarge the source between the size check and transfer.
                    size = await db.scalar(select(func.octet_length(cast(ScriptVersion.dag, Text))).where(
                        ScriptVersion.id == version_id, ScriptVersion.org_id == org_id,
                    ).with_for_update(nowait=True, read=not apply))
                    if size is None or size > max_source_bytes:
                        raise ValueError("source_unavailable_or_over_budget")
                    stmt = select(ScriptVersion.id, ScriptVersion.dag, ScriptVersion.dag_hash,
                                  ScriptVersion.node_count, ScriptVersion.updated_at).where(
                        ScriptVersion.id == version_id, ScriptVersion.org_id == org_id,
                    )
                    if apply:
                        stmt = stmt.with_for_update(nowait=True)
                    row = (await db.execute(stmt)).one_or_none()
                    if row is None:
                        raise ValueError("source_unavailable_or_over_budget")
                    # Also bound Python's representation of the locked JSONB.
                    if len(json.dumps(row.dag, ensure_ascii=False).encode()) > max_source_bytes:
                        raise ValueError("source_unavailable_or_over_budget")
                    dag_hash, node_count = _compute_dag_metadata(row.dag)
                    if (row.dag_hash, row.node_count) != (dag_hash, node_count):
                        result["would_update"] += 1
                        if apply:
                            await db.execute(update(ScriptVersion).where(
                                ScriptVersion.id == version_id, ScriptVersion.org_id == org_id,
                            ).values(dag_hash=dag_hash, node_count=node_count, updated_at=row.updated_at))
                            await db.commit()
                            result["updated"] += 1
            except DBAPIError as error:
                code = getattr(error.orig, "sqlstate", None)
                if code not in ("55P03", "57014"):
                    raise
                result["stopped"] = "contested_version" if code == "55P03" else "query_budget"
                return result  # Cursor does not cross a contested row.
            except ValueError:
                result["failed"] += 1
                if len(result["failures"]) < 50:
                    result["failures"].append({"version_id": str(version_id), "code": "source_invalid_or_over_budget"})
            result["scanned"] += 1
            cursor = version_id
            result["after"] = str(cursor)
    else:
        result["stopped"] = "version_budget" if result["scanned"] >= max_versions else "time_budget"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", type=uuid.UUID, required=True)
    parser.add_argument("--after", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reconcile", action="store_true", help="Also verify populated pairs against stored source")
    parser.add_argument("--max-versions", type=int, default=1000)
    parser.add_argument("--max-seconds", type=float, default=60)
    parser.add_argument("--max-source-bytes", type=int, default=8 * 1024 * 1024)
    args = parser.parse_args()
    async def run() -> dict:
        result = await backfill(AsyncSessionLocal, **vars(args))
        result["readiness"] = await metadata_readiness(AsyncSessionLocal, org_id=args.org_id)
        return result

    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["failed"] == 0 and result["stopped"] == "complete" and (not args.apply or result["readiness"]["catalog_ready"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
