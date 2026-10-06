"""Privileged maintenance writers: preserve source, append a version, pin the parent.

This is not an HTTP admission or runtime validation path. Historical generators
and seeds preserve their source format; interactive edits use ScriptService's
normal validation. Maintenance must name the tenant and expected current version.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.script import Script, ScriptVersion
from backend.services.script_service import ScriptService, _compute_dag_metadata


async def publish_preserved_source(
    db: AsyncSession,
    *,
    org_id: uuid.UUID,
    script_id: uuid.UUID,
    expected_current_version_id: uuid.UUID | None,
    dag: dict,
    notes: str,
) -> ScriptVersion:
    """Never mutate a saved DAG, commit, infer a tenant or choose a latest source."""
    _compute_dag_metadata(dag)  # Reject missing/non-array nodes before any write.
    service = ScriptService(db)
    script = await service._get_script(script_id, org_id, for_write=True)
    service._check_active(script)
    if script.current_version_id != expected_current_version_id:
        raise HTTPException(status_code=409, detail="Current script version changed; refresh before retrying")
    version = ScriptVersion(
        script_id=script.id, org_id=org_id,
        version=await service._get_latest_version_number(script.id) + 1,
        dag=dag, notes=notes,
    )
    db.add(version)
    await service.populate_version_metadata(version)
    script.current_version_id = version.id
    return version


async def seed_preserved_source(
    db: AsyncSession, *, org_id: uuid.UUID, name: str, dag: dict, notes: str,
) -> tuple[Script, ScriptVersion, bool]:
    """Keep legacy seed source; existing parents use the same contested-write fence."""
    from sqlalchemy import select

    script = await db.scalar(select(Script).where(
        Script.org_id == org_id, Script.name == name, Script.is_archived.is_(False),
    ).order_by(Script.id))
    created = script is None
    if script is None:
        script = Script(org_id=org_id, name=name, description=dag.get("description"), is_archived=False)
        db.add(script)
        await db.flush()
    version = await publish_preserved_source(
        db, org_id=org_id, script_id=script.id,
        expected_current_version_id=script.current_version_id, dag=dag, notes=notes,
    )
    return script, version, created
