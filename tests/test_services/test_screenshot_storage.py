# tests/test_services/test_screenshot_storage.py
# TZ-04 SPLIT-5: Unit-тесты для ScreenshotStorage (MinIO/S3).
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.screenshot_storage import BUCKET, ScreenshotStorage


@pytest.fixture
def minio():
    client = MagicMock()
    client.put_object = MagicMock()
    client.presigned_get_object = MagicMock(return_value="https://minio.local/signed-url")
    client.remove_object = MagicMock()
    return client


@pytest.fixture
def storage(minio):
    return ScreenshotStorage(minio, presign_ttl=3600)


class TestUploadScreenshot:
    @pytest.mark.asyncio
    async def test_upload_returns_object_key(self, storage, minio):
        key = await storage.upload_screenshot("task-1", "dev-1", "node-1", b"\xFF\xD8\xFF")
        assert key.startswith("tasks/task-1/dev-1/node-1/")
        assert key.endswith(".jpg")

    @pytest.mark.asyncio
    async def test_upload_calls_put_object_with_correct_bucket(self, storage, minio):
        await storage.upload_screenshot("tid", "did", "nid", b"imgdata")
        call_args = minio.put_object.call_args
        assert call_args[0][0] == BUCKET   # bucket name

    @pytest.mark.asyncio
    async def test_upload_passes_correct_content_type(self, storage, minio):
        await storage.upload_screenshot("t", "d", "n", b"x")
        _, kwargs = minio.put_object.call_args
        assert kwargs.get("content_type") == "image/jpeg"

    @pytest.mark.asyncio
    async def test_upload_passes_correct_data_length(self, storage, minio):
        data = b"test_image_bytes_1234"
        await storage.upload_screenshot("t", "d", "n", data)
        call_args = minio.put_object.call_args
        # 4th positional argument is length
        assert call_args[0][3] == len(data)


class TestGetPresignedUrl:
    @pytest.mark.asyncio
    async def test_returns_url_from_client(self, storage, minio):
        url = await storage.get_presigned_url("tasks/t/d/n/123.jpg")
        assert url == "https://minio.local/signed-url"

    @pytest.mark.asyncio
    async def test_calls_presigned_get_object_with_correct_args(self, storage, minio):
        from datetime import timedelta
        key = "tasks/abc/def/ghi/ts.jpg"
        await storage.get_presigned_url(key)
        call_args = minio.presigned_get_object.call_args
        assert call_args[0][0] == BUCKET
        assert call_args[0][1] == key
        assert call_args[1]["expires"] == timedelta(seconds=3600)


class TestDeleteScreenshot:
    @pytest.mark.asyncio
    async def test_delete_calls_remove_object(self, storage, minio):
        key = "tasks/t/d/n/old.jpg"
        await storage.delete_screenshot(key)
        minio.remove_object.assert_called_once_with(BUCKET, key)
