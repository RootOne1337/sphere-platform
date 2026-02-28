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

import structlog
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.script import Script, ScriptVersion
from backend.schemas.dag import DAGScript
from backend.schemas.script import CreateScriptRequest, UpdateScriptRequest

logger = structlog.get_logger()


def _compute_dag_hash(dag_dict: dict) -> str:
    """SHA256 от канонического JSON DAG (sort_keys для детерминизма)."""
    return hashlib.sha256(
        json.dumps(dag_dict, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


class ScriptService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Вспомогательные ─────────────────────────────────────────────────────

    async def _get_script(
        self, script_id: uuid.UUID, org_id: uuid.UUID
    ) -> Script:
        """Загрузить скрипт, проверить принадлежность org. 404 если не найден."""
        script = await self.db.scalar(
            select(Script)
            .where(Script.id == script_id, Script.org_id == org_id)
            .options(selectinload(Script.current_version))
        )
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
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
        await self.db.flush()

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
        script = await self._get_script(script_id, org_id)

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
            await self.db.flush()
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
    ) -> tuple[list[Script], int]:
        stmt = (
            select(Script)
            .where(Script.org_id == org_id, Script.is_archived.is_(False))
            .options(selectinload(Script.current_version))
        )

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
                    stmt.order_by(Script.updated_at.desc())
                    .offset((page - 1) * per_page)
                    .limit(per_page)
                )
            ).scalars().all()
        )

        return items, count

    async def archive_script(
        self, script_id: uuid.UUID, org_id: uuid.UUID
    ) -> None:
        """Soft-delete через is_archived=True."""
        script = await self._get_script(script_id, org_id)
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

    async def rollback_to_version(
        self,
        script_id: uuid.UUID,
        version_id: uuid.UUID,
        org_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Script:
        """Откатить скрипт к более ранней версии (создаёт новую)."""
        script = await self._get_script(script_id, org_id)
        old_version = await self.db.get(ScriptVersion, version_id)

        if not old_version or old_version.script_id != script_id:
            raise HTTPException(status_code=404, detail="Version not found")

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
        await self.db.flush()
        script.current_version_id = rollback_version.id

        logger.info(
            "script.rollback",
            script_id=str(script_id),
            to_version=old_version.version,
            new_version=last_num + 1,
        )
        return script
