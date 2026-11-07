"""A rerun is a new, independently queued execution of the original context."""
import copy
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.api.v1.tasks.router import get_task_service
from backend.main import app
from backend.models.script import ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.services.task_service import TaskService


@pytest.fixture(autouse=True)
def authorized_tasks(test_user, db_session, monkeypatch):
    test_user.role = "org_admin"

    @asynccontextmanager
    async def audit_session():
        yield db_session

    monkeypatch.setattr("backend.middleware.audit.AsyncSessionLocal", audit_session)


async def seed(db, org, device, sample_script, status=TaskStatus.FAILED):
    script, version = sample_script
    original = Task(org_id=org.id, device_id=device.id, script_id=script.id,
                    script_version_id=version.id, status=status, priority=2,
                    timeout_seconds=123, input_params={"priority": 2, "custom": {"region": ["eu"]},
                    "webhook_url": "https://callback.example/test"}, result={"old": "receipt"})
    db.add(original)
    await db.flush()
    return original


async def test_rerun_keeps_pinned_version_inputs_timeout_and_new_identity(
    authenticated_client, db_session, test_org, test_device, sample_script,
):
    original = await seed(db_session, test_org, test_device, sample_script)
    script, version = sample_script
    newer = ScriptVersion(org_id=test_org.id, script_id=script.id, version=2,
                          dag=version.dag, notes="newer")
    db_session.add(newer)
    await db_session.flush()
    script.current_version_id = newer.id
    original_inputs = copy.deepcopy(original.input_params)
    app.dependency_overrides[get_task_service] = lambda: TaskService(db_session)
    response = await authenticated_client.post(f"/api/v1/tasks/{original.id}/rerun")
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["id"] != str(original.id)
    assert data["script_version_id"] == str(version.id)
    assert data["input_params"] == original_inputs
    assert data["priority"] == 2 and data["status"] == "queued"
    created = await db_session.get(Task, uuid.UUID(data["id"]))
    assert created.timeout_seconds == 123
    assert created.result is None and created.started_at is None
    assert created.batch_id is None and created.wave_index is None
    assert original.result == {"old": "receipt"}
    duplicate = await authenticated_client.post(f"/api/v1/tasks/{original.id}/rerun")
    assert duplicate.status_code == 409


@pytest.mark.parametrize("status", [TaskStatus.QUEUED, TaskStatus.ASSIGNED, TaskStatus.RUNNING])
async def test_active_task_cannot_be_rerun(authenticated_client, db_session, test_org, test_device, sample_script, status):
    original = await seed(db_session, test_org, test_device, sample_script, status)
    app.dependency_overrides[get_task_service] = lambda: TaskService(db_session)
    result = await authenticated_client.post(f"/api/v1/tasks/{original.id}/rerun")
    assert result.status_code == 409
    assert len(list(await db_session.scalars(select(Task)))) == 1


async def test_rerun_requires_owned_source(authenticated_client, db_session):
    svc = TaskService(db_session)
    app.dependency_overrides[get_task_service] = lambda: svc
    response = await authenticated_client.post(f"/api/v1/tasks/{uuid.uuid4()}/rerun")
    assert response.status_code == 404


async def test_legacy_task_without_version_is_not_reinterpreted(db_session, test_org, test_device, sample_script):
    original = await seed(db_session, test_org, test_device, sample_script)
    original.script_version_id = None
    svc = TaskService(db_session)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await svc.rerun_task(original.id, test_org.id)
    assert error.value.status_code == 409


async def test_rerun_context_is_deep_copied_and_never_published_before_commit(db_session, test_org, test_device, sample_script):
    original = await seed(db_session, test_org, test_device, sample_script)
    queue, publisher = AsyncMock(), AsyncMock()
    created = await TaskService(db_session, queue, publisher=publisher).rerun_task(original.id, test_org.id)
    created.input_params["custom"]["region"].append("us")
    assert original.input_params["custom"]["region"] == ["eu"]
    queue.enqueue.assert_not_awaited()
    publisher.send_command_live.assert_not_awaited()


async def test_viewer_cannot_rerun(authenticated_client, db_session, test_user, test_org, test_device, sample_script):
    original = await seed(db_session, test_org, test_device, sample_script)
    test_user.role = "viewer"
    app.dependency_overrides[get_task_service] = lambda: TaskService(db_session)
    response = await authenticated_client.post(f"/api/v1/tasks/{original.id}/rerun")
    assert response.status_code == 403
    assert len(list(await db_session.scalars(select(Task)))) == 1


@pytest.mark.parametrize("invalid_context", ["missing_account", "invalid_account", "missing_version", "archived_script"])
async def test_unavailable_original_context_never_falls_back_to_current(db_session, test_org, test_device, sample_script, invalid_context):
    from fastapi import HTTPException
    original = await seed(db_session, test_org, test_device, sample_script)
    if invalid_context == "missing_account":
        original.input_params = {**original.input_params, "account_id": str(uuid.uuid4())}
    if invalid_context == "invalid_account":
        original.input_params = {**original.input_params, "account_id": "broken"}
    if invalid_context == "missing_version":
        original.script_version_id = uuid.uuid4()
    if invalid_context == "archived_script":
        sample_script[0].is_archived = True
    with pytest.raises(HTTPException) as error:
        await TaskService(db_session).rerun_task(original.id, test_org.id)
    assert error.value.status_code in (404, 409)
    assert len(list(await db_session.scalars(select(Task)))) == 1
