"""Opt-in real S3 read through the authenticated HTTP task routes."""
import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest
from minio import Minio
from pydantic import SecretStr

from backend.api.v1.tasks import router as task_router
from backend.core.config import settings
from backend.main import app
from backend.services.screenshot_storage import BUCKET, ScreenshotStorage
from backend.services.task_screenshots import get_screenshot_storage


async def test_real_minio_object_manifest_authenticated_read_and_expiration(
    authenticated_client, test_user, test_org, test_device, monkeypatch,
):
    endpoint = os.environ.get("SPHERE_TEST_MINIO_ENDPOINT")
    if not endpoint:
        pytest.skip("Set SPHERE_TEST_MINIO_* for a disposable MinIO service")
    assert endpoint.startswith("127.0.0.1:"), "Only disposable loopback storage is allowed"
    test_user.role = "org_admin"
    client = Minio(endpoint, access_key=os.environ["SPHERE_TEST_MINIO_USER"],
                   secret_key=os.environ["SPHERE_TEST_MINIO_PASSWORD"], secure=False, region="us-east-1")
    await asyncio.to_thread(client.make_bucket, BUCKET)
    storage = ScreenshotStorage(client)
    task = SimpleNamespace(id=uuid.uuid4(), device_id=test_device.id, org_id=test_org.id, result={})

    async def owned(task_id, org_id):
        assert task_id == task.id and org_id == test_org.id
        return task

    app.dependency_overrides[task_router.get_task_service] = lambda: SimpleNamespace(_get_task=owned)
    monkeypatch.setattr(settings, "SCREENSHOT_STORAGE_ENDPOINT", endpoint)
    monkeypatch.setattr(settings, "SCREENSHOT_STORAGE_ACCESS_KEY", SecretStr(os.environ["SPHERE_TEST_MINIO_USER"]))
    monkeypatch.setattr(settings, "SCREENSHOT_STORAGE_SECRET_KEY", SecretStr(os.environ["SPHERE_TEST_MINIO_PASSWORD"]))
    monkeypatch.setattr(settings, "SCREENSHOT_STORAGE_SECURE", False)
    get_screenshot_storage.cache_clear()
    image = b"\xff\xd8\xfftest-object-bytes"
    key = await storage.upload_screenshot(str(task.id), str(task.device_id), "capture", image)
    task.result = {"node_logs": [{"screenshot_key": key}]}
    try:
        manifest = (await authenticated_client.get(f"/api/v1/tasks/{task.id}/screenshots")).json()
        content_url = manifest["screenshots"][0]["url"]
        read = await authenticated_client.get(f"/api/v1{content_url}")
        assert read.status_code == 200 and read.content == image
        assert read.headers["content-type"] == "image/jpeg"
        await storage.delete_screenshot(key)
        expired = await authenticated_client.get(f"/api/v1{content_url}")
        assert expired.status_code == 404
        assert "missing or expired" in expired.json()["detail"]
    finally:
        await storage.delete_screenshot(key)
        get_screenshot_storage.cache_clear()
