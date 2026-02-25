# tests/test_scripts/conftest.py
# Фикстуры для TZ-04 Script Engine тестов.
from __future__ import annotations

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.script import Script, ScriptVersion

# ── Фикстуры Script Engine ────────────────────────────────────────────────────

SAMPLE_DAG = {
    "version": "1.0",
    "name": "Sample DAG",
    "description": "Tap and sleep test",
    "nodes": [
        {"id": "start", "action": {"type": "start"}, "on_success": "tap1"},
        {
            "id": "tap1",
            "action": {"type": "tap", "x": 540, "y": 960},
            "on_success": "sleep1",
            "retry": 2,
        },
        {
            "id": "sleep1",
            "action": {"type": "sleep", "ms": 500},
            "on_success": "end",
        },
        {"id": "end", "action": {"type": "end", "status": "success"}},
    ],
    "entry_node": "start",
}


@pytest_asyncio.fixture
async def sample_script(db_session: AsyncSession, test_org, test_user):
    """Скрипт с одной версией и валидным DAG."""
    from backend.schemas.dag import DAGScript

    dag_obj = DAGScript.model_validate(SAMPLE_DAG)
    dag_dict = dag_obj.model_dump()

    script = Script(
        org_id=test_org.id,
        name="Sample Script",
        description="Test script",
    )
    db_session.add(script)
    await db_session.flush()

    version = ScriptVersion(
        script_id=script.id,
        org_id=test_org.id,
        version=1,
        dag=dag_dict,
        notes="Initial version",
        created_by_id=test_user.id,
    )
    db_session.add(version)
    await db_session.flush()

    script.current_version_id = version.id

    return script, version
