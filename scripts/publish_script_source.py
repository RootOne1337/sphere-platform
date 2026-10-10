"""Explicit, version-pinned maintenance publishing for legacy generators/patches.

Dry-run by default. Preserves legacy source format; this is privileged DB
maintenance, not authenticated HTTP editing or an Android runtime test.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import uuid
from pathlib import Path

from fastapi import HTTPException

from backend.database.engine import AsyncSessionLocal
from backend.database.tenant import bind_tenant_context
from backend.services.script_service import ScriptService, _compute_dag_metadata
from backend.services.script_version_admin import publish_preserved_source

PATCHES = ("fix_sleep_wait", "fix_dag_v2", "fix_dag_add_validate")


def patch_source(dag: dict, patch: str) -> dict:
    source = copy.deepcopy(dag)
    _compute_dag_metadata(source)

    def node(name: str) -> dict:
        matches = [n for n in source["nodes"] if isinstance(n, dict) and n.get("id") == name]
        if len(matches) != 1:
            raise ValueError("Patch target must exist exactly once")
        return matches[0]

    if patch == "fix_sleep_wait":
        node("sleep_wait")["on_failure"] = "check_game_alive"
    elif patch == "fix_dag_v2":
        node("scan_all")["action"]["fail_if_not_found"] = True
        node("route_play")["action"]["on_true"] = "sleep_wait"
        node("check_watchdog")["action"]["code"] = "return true"
    elif patch == "fix_dag_add_validate":
        if any(n.get("id") == "validate_game_pid" for n in source["nodes"] if isinstance(n, dict)):
            raise ValueError("Patch target already exists")
        source["nodes"].append({
            "id": "validate_game_pid", "retry": 0, "timeout_ms": 2000,
            "action": {"type": "condition", "code": "local pid = tostring(ctx.game_pid or '')\nreturn #pid > 0 and pid ~= 'nil'",
                       "on_true": "reset_dead_alive", "on_false": "increment_dead_count"},
            "on_success": "reset_dead_alive", "on_failure": "increment_dead_count",
        })
    else:
        raise ValueError("Unknown maintenance patch")
    return source


async def publish(
    dag: dict | None, *, org_id: uuid.UUID, script_id: uuid.UUID,
    expected_version_id: uuid.UUID, apply: bool = False, patch: str | None = None,
) -> dict:
    async with AsyncSessionLocal() as db:
        await bind_tenant_context(db, str(org_id))
        service = ScriptService(db)
        script = await service.get_script(script_id, org_id)
        service._check_active(script)
        if script.current_version_id != expected_version_id:
            raise HTTPException(status_code=409, detail="Current script version changed; refresh before retrying")
        if patch is not None:
            version = await service.get_version(script_id, expected_version_id, org_id)
            dag = patch_source(version.dag, patch)
        if not isinstance(dag, dict):
            raise ValueError("Maintenance source must be an object")
        dag_hash, node_count = _compute_dag_metadata(dag)
        receipt = {"schema": 1, "org_id": str(org_id), "script_id": str(script_id),
                   "expected_version_id": str(expected_version_id), "apply": apply,
                   "node_count": node_count, "input_hash": dag_hash,
                   "source_rewritten": False, "tasks_created": 0,
                   "scope": "privileged-preserved-source-maintenance-no-runtime-acceptance"}
        if apply:
            new_version = await publish_preserved_source(
                db, org_id=org_id, script_id=script_id,
                expected_current_version_id=expected_version_id, dag=dag,
                notes=f"Maintenance publication: {patch or 'generated source'}",
            )
            await db.commit()
            receipt.update(version_id=str(new_version.id), version=new_version.version,
                           stored_hash=new_version.dag_hash, node_count=new_version.node_count)
        return receipt


def generated_main(dag: dict | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org-id", type=uuid.UUID, required=True)
    parser.add_argument("--script-id", type=uuid.UUID, required=True)
    parser.add_argument("--expected-version-id", type=uuid.UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    if dag is None:
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--source", type=Path)
        group.add_argument("--patch", choices=PATCHES)
    args = parser.parse_args()
    source = getattr(args, "source", None)
    patch = getattr(args, "patch", None)
    if source is not None:
        with source.open("rb") as handle:
            raw = handle.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024:
            parser.error("Source exceeds 512 KiB maintenance input limit")
        dag = json.loads(raw.decode("utf-8-sig"))
    receipt = asyncio.run(publish(dag, org_id=args.org_id, script_id=args.script_id,
                                 expected_version_id=args.expected_version_id, apply=args.apply, patch=patch))
    print(json.dumps(receipt))
    return 0


if __name__ == "__main__":
    raise SystemExit(generated_main())
