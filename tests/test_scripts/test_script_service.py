# tests/test_scripts/test_script_service.py
# SPLIT-2 критерии готовности.
from __future__ import annotations

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.script import CreateScriptRequest, UpdateScriptRequest
from backend.services.script_service import ScriptService, _compute_dag_hash
from tests.test_scripts.conftest import SAMPLE_DAG


class TestScriptServiceCreate:
    async def test_create_script_success(self, db_session: AsyncSession, test_org, test_user):
        svc = ScriptService(db_session)
        req = CreateScriptRequest(
            name="My Script",
            description="Desc",
            dag=SAMPLE_DAG,
            changelog="Initial",
        )
        script = await svc.create_script(test_org.id, test_user.id, req)
        assert script.id is not None
        assert script.name == "My Script"
        assert script.current_version_id is not None

    async def test_create_script_invalid_dag_raises_422(
        self, db_session: AsyncSession, test_org, test_user
    ):
        from fastapi import HTTPException

        svc = ScriptService(db_session)
        req = CreateScriptRequest(
            name="Bad",
            dag={"version": "1.0", "name": "x", "nodes": [], "entry_node": "?"},
        )
        with pytest.raises(HTTPException) as exc_info:
            await svc.create_script(test_org.id, test_user.id, req)
        assert exc_info.value.status_code == 422


class TestScriptServiceUpdate:
    async def test_update_dag_creates_new_version(
        self, db_session: AsyncSession, test_org, test_user, sample_script
    ):
        script, version = sample_script
        svc = ScriptService(db_session)

        modified_dag = {
            **SAMPLE_DAG,
            "name": "Modified DAG",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "end"},
                {"id": "end", "action": {"type": "end"}},
            ],
        }
        req = UpdateScriptRequest(dag=modified_dag, changelog="Version 2")
        updated = await svc.update_script(script.id, test_org.id, test_user.id, req)

        # Новая версия должна быть создана
        assert updated.current_version_id != version.id

    async def test_update_same_dag_no_new_version(
        self, db_session: AsyncSession, test_org, test_user, sample_script
    ):
        script, version = sample_script
        svc = ScriptService(db_session)

        # Обновить тот же DAG — версия не должна измениться
        req = UpdateScriptRequest(dag=SAMPLE_DAG)
        updated = await svc.update_script(script.id, test_org.id, test_user.id, req)

        assert updated.current_version_id == version.id


class TestScriptServiceSearch:
    async def test_list_excludes_archived(
        self, db_session: AsyncSession, test_org, test_user, sample_script
    ):
        script, _ = sample_script
        svc = ScriptService(db_session)

        # Архивировать
        await svc.archive_script(script.id, test_org.id)

        scripts, total = await svc.list_scripts(test_org.id)
        ids = [s.id for s in scripts]
        assert script.id not in ids

    async def test_list_with_query(
        self, db_session: AsyncSession, test_org, test_user
    ):
        svc = ScriptService(db_session)
        req = CreateScriptRequest(
            name="Unique_XYZ_Script",
            dag=SAMPLE_DAG,
        )
        script = await svc.create_script(test_org.id, test_user.id, req)

        scripts, total = await svc.list_scripts(test_org.id, query="Unique_XYZ")
        assert any(s.id == script.id for s in scripts)


class TestScriptServiceRollback:
    async def test_rollback_creates_new_version(
        self, db_session: AsyncSession, test_org, test_user, sample_script
    ):
        script, version_1 = sample_script
        svc = ScriptService(db_session)

        # Создать версию 2
        modified_dag = {
            **SAMPLE_DAG,
            "name": "V2",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "end"},
                {"id": "end", "action": {"type": "end"}},
            ],
        }
        req = UpdateScriptRequest(dag=modified_dag)
        await svc.update_script(script.id, test_org.id, test_user.id, req)

        # Откатить к версии 1
        rolled_back = await svc.rollback_to_version(
            script.id, version_1.id, test_org.id, test_user.id
        )

        # Должна быть создана новая версия (≠ version_1.id, но DAG такой же)
        assert rolled_back.current_version_id != version_1.id

    async def test_rollback_unknown_version_raises_404(
        self, db_session: AsyncSession, test_org, test_user, sample_script
    ):
        import uuid
        from fastapi import HTTPException

        script, _ = sample_script
        svc = ScriptService(db_session)

        with pytest.raises(HTTPException) as exc_info:
            await svc.rollback_to_version(
                script.id, uuid.uuid4(), test_org.id, test_user.id
            )
        assert exc_info.value.status_code == 404
