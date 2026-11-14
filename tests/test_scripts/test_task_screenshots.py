"""Screenshots belong to an authorized task, not to a guessed public object URL."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.api.v1.tasks import router as task_router
from backend.main import app


@pytest.fixture
def screenshot_task(test_org, test_device, test_user):
    test_user.role = "org_admin"
    task_id = uuid.uuid4()
    key = f"tasks/{task_id}/{test_device.id}/capture/123.jpg"
    return SimpleNamespace(id=task_id, device_id=test_device.id, org_id=test_org.id,
                           result={"node_logs": [{"screenshot_key": key}], "final_screenshot_key": key})


def service_for(task, org_id):
    from fastapi import HTTPException

    async def owned(task_id, current_org):
        if task_id != task.id or current_org != org_id:
            raise HTTPException(404, "Task not found")
        return task

    return SimpleNamespace(_get_task=owned)


async def test_manifest_identifies_task_deduplicates_keys_and_uses_authenticated_content_route(
    authenticated_client, screenshot_task, test_org,
):
    task = screenshot_task
    app.dependency_overrides[task_router.get_task_service] = lambda: service_for(task, test_org.id)
    response = await authenticated_client.get(f"/api/v1/tasks/{task.id}/screenshots")
    assert response.status_code == 200
    manifest = response.json()
    assert manifest["task_id"] == str(task.id)
    assert len(manifest["screenshots"]) == 1
    entry = manifest["screenshots"][0]
    assert entry["key"] == task.result["final_screenshot_key"]
    assert entry["url"].startswith(f"/tasks/{task.id}/screenshots/content?key=tasks%2F")


async def test_content_uses_owned_storage_key_and_never_public_storage_address(
    authenticated_client, screenshot_task, test_org, monkeypatch,
):
    task = screenshot_task
    app.dependency_overrides[task_router.get_task_service] = lambda: service_for(task, test_org.id)
    storage = SimpleNamespace(read_screenshot=AsyncMock(return_value=(b"\xff\xd8\xffimage", "image/jpeg")))
    monkeypatch.setattr(task_router, "get_screenshot_storage", lambda: storage, raising=False)
    result = await authenticated_client.get(f"/api/v1/tasks/{task.id}/screenshots/content",
                                            params={"key": task.result["final_screenshot_key"]})
    assert result.status_code == 200
    assert result.content == b"\xff\xd8\xffimage"
    assert result.headers["content-type"] == "image/jpeg"
    assert result.headers["cache-control"] == "private, no-store"
    assert result.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("bad_key", ["tasks/other-device/other-task/img.jpg", "../../secret.jpg", "https://other.example/img.jpg"])
async def test_reported_but_foreign_or_unsafe_key_never_reaches_storage(
    authenticated_client, screenshot_task, test_org, monkeypatch, bad_key,
):
    task = screenshot_task
    task.result["final_screenshot_key"] = bad_key
    app.dependency_overrides[task_router.get_task_service] = lambda: service_for(task, test_org.id)
    factory = AsyncMock()
    monkeypatch.setattr(task_router, "get_screenshot_storage", factory, raising=False)
    result = await authenticated_client.get(f"/api/v1/tasks/{task.id}/screenshots/content", params={"key": bad_key})
    assert result.status_code == 404
    factory.assert_not_called()


async def test_missing_storage_is_an_explicit_503_not_a_raw_key_success(
    authenticated_client, screenshot_task, test_org, monkeypatch,
):
    from fastapi import HTTPException
    task = screenshot_task
    app.dependency_overrides[task_router.get_task_service] = lambda: service_for(task, test_org.id)

    def unavailable():
        raise HTTPException(503, "Screenshot storage is not configured")

    monkeypatch.setattr(task_router, "get_screenshot_storage", unavailable, raising=False)
    result = await authenticated_client.get(f"/api/v1/tasks/{task.id}/screenshots/content",
                                            params={"key": task.result["final_screenshot_key"]})
    assert result.status_code == 503
    assert "not configured" in result.json()["detail"]


async def test_other_tenant_cannot_read_manifest_or_content(authenticated_client, screenshot_task, monkeypatch):
    task = screenshot_task
    app.dependency_overrides[task_router.get_task_service] = lambda: service_for(task, uuid.uuid4())
    factory = AsyncMock()
    monkeypatch.setattr(task_router, "get_screenshot_storage", factory, raising=False)
    for path in ["screenshots", "screenshots/content"]:
        result = await authenticated_client.get(f"/api/v1/tasks/{task.id}/{path}",
                                                params={"key": task.result["final_screenshot_key"]})
        assert result.status_code == 404
    factory.assert_not_called()
