# backend/services/script_service.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-2. Script CRUD с полным версионированием.
#
# Особенности:
#   — Каждое изменение DAG создаёт новую неизменяемую ScriptVersion
#   — Дедупликация по SHA256 хешу DAG (без лишних версий)
#   — Rollback к старой версии создаёт новую версию с тем же DAG
#   — Soft-delete через is_archived=True
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Literal

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.script import Script, ScriptVersion
from backend.schemas.dag import DAGScript
from backend.schemas.script import CreateScriptRequest, ScriptCatalogItem, UpdateScriptRequest

logger = structlog.get_logger()


def _compute_dag_hash(dag_dict: dict) -> str:
    """SHA256 от канонического JSON DAG (sort_keys для детерминизма)."""
    return hashlib.sha256(
        json.dumps(dag_dict, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _compute_dag_metadata(dag_dict: dict) -> tuple[str, int]:
    """Derive metadata without normalizing historical source or inventing a count."""
    if not isinstance(dag_dict, dict) or not isinstance(dag_dict.get("nodes"), list):
        raise ValueError("Stored DAG nodes must be an array")
    return _compute_dag_hash(dag_dict), len(dag_dict["nodes"])


def _script_catalog_statement(
    org_id: uuid.UUID,
    query: str | None,
    page: int,
    per_page: int,
    state: Literal["active", "archived", "all"],
):
    """Explicit scalar projection; the count survives an empty offset page."""
    filtered = select(
        Script.id, Script.org_id, Script.name, Script.description, Script.is_archived,
        Script.created_at, Script.updated_at, Script.current_version_id,
    ).where(Script.org_id == org_id)
    if state != "all":
        filtered = filtered.where(Script.is_archived.is_(state == "archived"))
    if query:
        filtered = filtered.where(or_(
            Script.name.ilike(f"%{query}%"), Script.description.ilike(f"%{query}%"),
        ))
    candidates = filtered.cte("catalog_scripts")
    count = select(func.count().label("total")).select_from(candidates).cte("catalog_count")
    page_rows = (
        select(*candidates.c).order_by(candidates.c.updated_at.desc(), candidates.c.id)
        .offset((page - 1) * per_page).limit(per_page).cte("catalog_page")
    )
    versions = ScriptVersion.__table__
    owned_page = page_rows.outerjoin(versions, and_(
        page_rows.c.current_version_id == versions.c.id,
        versions.c.script_id == page_rows.c.id,
        versions.c.org_id == page_rows.c.org_id,
        versions.c.org_id == org_id,
    ))
    return select(
        count.c.total, *page_rows.c,
        versions.c.id.label("version_id"),
        versions.c.script_id.label("version_script_id"),
        versions.c.version.label("version_number"),
        versions.c.dag_hash, versions.c.node_count,
        versions.c.created_at.label("version_created_at"),
    ).select_from(count.outerjoin(owned_page, true())).order_by(
        page_rows.c.updated_at.desc(), page_rows.c.id,
    )


class ScriptService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Вспомогательные ─────────────────────────────────────────────────────

    async def _get_script(
        self, script_id: uuid.UUID, org_id: uuid.UUID, *, for_write: bool = False, for_run: bool = False
    ) -> Script:
        """Загрузить скрипт, проверить принадлежность org. 404 если не найден."""
        stmt = (
            select(Script)
            .where(Script.id == script_id, Script.org_id == org_id)
            .options(selectinload(Script.current_version))
        )
        if for_write or for_run:
            # Lock the parent until commit before allocating a version or archiving.
            # Refresh a previously loaded identity: READ COMMITTED must see the winner.
            stmt = stmt.with_for_update(nowait=True, read=for_run).execution_options(populate_existing=True)
        try:
            script = await self.db.scalar(stmt)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "55P03":
                raise
            await self.db.rollback()
            raise HTTPException(status_code=409, detail="Script is being changed; refresh before retrying") from exc
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        return script

    @staticmethod
    def _check_current(script: Script, expected_current_version_id: uuid.UUID | None) -> None:
        if expected_current_version_id is not None and script.current_version_id != expected_current_version_id:
            raise HTTPException(status_code=409, detail="Current script version changed; refresh before retrying")

    @staticmethod
    def _check_active(script: Script) -> None:
        if script.is_archived:
            raise HTTPException(status_code=409, detail="Archived script cannot be changed")

    async def get_for_run(self, script_id: uuid.UUID, org_id: uuid.UUID, expected: uuid.UUID) -> Script:
        # Shared locks let independent device admissions coexist, while preventing
        # update/archive from changing the inspected version until admission commits.
        script = await self._get_script(script_id, org_id, for_run=True)
        self._check_active(script)
        self._check_current(script, expected)
        return script

    async def _get_latest_version_number(self, script_id: uuid.UUID) -> int:
        """Получить максимальный номер версии для скрипта."""
        result = await self.db.scalar(
            select(func.max(ScriptVersion.version)).where(
                ScriptVersion.script_id == script_id
            )
        )
        return result or 0

    def _validate_dag(self, dag_raw: dict) -> tuple[dict, str]:
        """
        Валидировать DAG через Pydantic, вернуть (serialized_dict, sha256_hash).
        Raises HTTPException 422 при невалидном DAG.
        """
        try:
            dag_obj = DAGScript.model_validate(dag_raw)
        except ValidationError as e:
            # Pydantic V2 errors() может содержать не-сериализуемые объекты в ctx
            import json as _json
            safe_errors = _json.loads(e.json())
            raise HTTPException(status_code=422, detail=safe_errors)

        dag_dict = dag_obj.model_dump()
        dag_hash = _compute_dag_hash(dag_dict)
        return dag_dict, dag_hash

    async def populate_version_metadata(self, version: ScriptVersion) -> None:
        # JSONB may change numeric representations. Hash exactly what a new
        # PostgreSQL read sees, before either metadata or the pointer commits.
        await self.db.flush()
        await self.db.refresh(version, attribute_names=["dag"])
        version.dag_hash, version.node_count = _compute_dag_metadata(version.dag)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    async def create_script(
        self,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        data: CreateScriptRequest,
    ) -> Script:
        dag_dict, _dag_hash = self._validate_dag(data.dag)

        script = Script(
            org_id=org_id,
            name=data.name,
            description=data.description,
        )
        self.db.add(script)
        await self.db.flush()  # получить id

        version = ScriptVersion(
            script_id=script.id,
            org_id=org_id,
            version=1,
            dag=dag_dict,
            notes=data.changelog or "Initial version",
            created_by_id=user_id,
        )
        self.db.add(version)
        await self.populate_version_metadata(version)

        script.current_version_id = version.id
        logger.info("script.created", script_id=str(script.id), org_id=str(org_id))
        return script

    async def update_script(
        self,
        script_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        data: UpdateScriptRequest,
    ) -> Script:
        script = await self._get_script(script_id, org_id, for_write=True)
        self._check_current(script, data.expected_current_version_id)
        self._check_active(script)

        if data.name is not None:
            script.name = data.name
        if data.description is not None:
            script.description = data.description

        if data.dag is not None:
            dag_dict, dag_hash = self._validate_dag(data.dag)

            # Дедупликация: не создавать версию если DAG не изменился
            if script.current_version_id:
                current_v = await self.db.get(ScriptVersion, script.current_version_id)
                if current_v:
                    current_hash = _compute_dag_hash(current_v.dag)
                    if current_hash == dag_hash:
                        logger.info(
                            "script.update.dag_unchanged",
                            script_id=str(script_id),
                        )
                        return script  # DAG идентичен, только метаданные обновились

            last_num = await self._get_latest_version_number(script_id)
            new_version = ScriptVersion(
                script_id=script_id,
                org_id=org_id,
                version=last_num + 1,
                dag=dag_dict,
                notes=data.changelog or f"Version {last_num + 1}",
                created_by_id=user_id,
            )
            self.db.add(new_version)
            await self.populate_version_metadata(new_version)
            script.current_version_id = new_version.id

        logger.info("script.updated", script_id=str(script_id))
        return script

    async def get_script(
        self,
        script_id: uuid.UUID,
        org_id: uuid.UUID,
        include_versions: bool = False,
    ) -> Script:
        opts = [selectinload(Script.current_version)]
        if include_versions:
            opts.append(selectinload(Script.versions))

        script = await self.db.scalar(
            select(Script)
            .where(Script.id == script_id, Script.org_id == org_id)
            .options(*opts)
        )
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        return script

    async def list_scripts(
        self,
        org_id: uuid.UUID,
        query: str | None = None,
        page: int = 1,
        per_page: int = 50,
        state: Literal["active", "archived", "all"] = "active",
    ) -> tuple[list[Script], int]:
        stmt = (
            select(Script)
            .where(Script.org_id == org_id)
            .options(selectinload(Script.current_version))
        )
        if state != "all":
            stmt = stmt.where(Script.is_archived.is_(state == "archived"))

        if query:
            stmt = stmt.where(
                or_(
                    Script.name.ilike(f"%{query}%"),
                    Script.description.ilike(f"%{query}%"),
                )
            )

        count = (
            await self.db.scalar(
                select(func.count()).select_from(stmt.subquery())
            )
        ) or 0

        items = list(
            (
                await self.db.execute(
                    stmt.order_by(Script.updated_at.desc(), Script.id)
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            ).scalars().all()
        )

        return items, count

    async def list_script_catalog(
        self,
        org_id: uuid.UUID,
        query: str | None = None,
        page: int = 1,
        per_page: int = 50,
        state: Literal["active", "archived", "all"] = "active",
    ) -> tuple[list[ScriptCatalogItem], int]:
        rows = (await self.db.execute(
            _script_catalog_statement(org_id, query, page, per_page, state)
        )).mappings().all()
        total = rows[0]["total"]
        items = []
        for row in rows:
            if row["id"] is None:  # count-only row for an empty page
                continue
            version = None
            if row["version_id"] is not None:
                version = {
                    "id": row["version_id"], "script_id": row["version_script_id"],
                    "version": row["version_number"], "dag_hash": row["dag_hash"],
                    "created_at": row["version_created_at"],
                }
            try:
                items.append(ScriptCatalogItem.model_validate({
                    "id": row["id"], "org_id": row["org_id"], "name": row["name"],
                    "description": row["description"], "is_archived": row["is_archived"],
                    "created_at": row["created_at"], "updated_at": row["updated_at"],
                    "current_version_id": row["current_version_id"],
                    "node_count": row["node_count"], "current_version": version,
                }))
            except ValidationError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "script_catalog_metadata_unavailable"},
                    headers={"Cache-Control": "no-store"},
                ) from exc
        return items, total

    async def archive_script(
        self, script_id: uuid.UUID, org_id: uuid.UUID,
        expected_current_version_id: uuid.UUID | None = None,
    ) -> None:
        """Soft-delete через is_archived=True."""
        script = await self._get_script(script_id, org_id, for_write=True)
        self._check_current(script, expected_current_version_id)
        script.is_archived = True
        logger.info("script.archived", script_id=str(script_id))

    async def list_versions(
        self, script_id: uuid.UUID, org_id: uuid.UUID
    ) -> list[ScriptVersion]:
        """Список всех версий скрипта (только для своей org)."""
        # Проверить владельца
        await self._get_script(script_id, org_id)
        versions = list(
            (
                await self.db.execute(
                    select(ScriptVersion)
                    .where(ScriptVersion.script_id == script_id)
                    .order_by(ScriptVersion.version.desc())
                )
            ).scalars().all()
        )
        return versions

    async def get_version(
        self, script_id: uuid.UUID, version_id: uuid.UUID, org_id: uuid.UUID,
    ) -> ScriptVersion:
        await self._get_script(script_id, org_id)
        version = await self.db.scalar(select(ScriptVersion).where(
            ScriptVersion.id == version_id, ScriptVersion.script_id == script_id,
            ScriptVersion.org_id == org_id,
        ))
        if version is None:
            raise HTTPException(status_code=404, detail="Version not found")
        return version

    async def rollback_to_version(
        self,
        script_id: uuid.UUID,
        version_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
        expected_current_version_id: uuid.UUID | None = None,
    ) -> Script:
        """Откатить скрипт к более ранней версии (создаёт новую)."""
        script = await self._get_script(script_id, org_id, for_write=True)
        self._check_current(script, expected_current_version_id)
        self._check_active(script)
        old_version = await self.get_version(script_id, version_id, org_id)

        last_num = await self._get_latest_version_number(script_id)
        rollback_version = ScriptVersion(
            script_id=script_id,
            org_id=org_id,
            version=last_num + 1,
            dag=old_version.dag,
            notes=f"Rollback to version {old_version.version}",
            created_by_id=user_id,
        )
        self.db.add(rollback_version)
        await self.populate_version_metadata(rollback_version)
        script.current_version_id = rollback_version.id

        logger.info(
            "script.rollback",
            script_id=str(script_id),
            to_version=old_version.version,
            new_version=last_num + 1,
        )
        return script
