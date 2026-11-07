# tests/test_services/test_screenshot_storage.py
# TZ-04 SPLIT-5: Unit-тесты для ScreenshotStorage (MinIO/S3).
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services.screenshot_storage import BUCKET, MAX_SCREENSHOT_BYTES, ScreenshotStorage


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


@pytest.mark.parametrize("data,mime", [(b"\xff\xd8\xffimage", "image/jpeg"),
                                      (b"\x89PNG\r\n\x1a\nimage", "image/png")])
async def test_private_read_detects_raster_type_and_closes_response(storage, minio, data, mime):
    response = MagicMock()
    response.read.return_value = data
    minio.get_object.return_value = response
    assert await storage.read_screenshot("tasks/owned.jpg") == (data, mime)
    response.read.assert_called_once_with(MAX_SCREENSHOT_BYTES + 1)
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


@pytest.mark.parametrize("data", [b"<html>not an image</html>", b"x" * (MAX_SCREENSHOT_BYTES + 1)], ids=["html", "oversized"])
async def test_rejected_content_still_releases_connection(storage, minio, data):
    response = MagicMock()
    response.read.return_value = data
    minio.get_object.return_value = response
    with pytest.raises(ValueError):
        await storage.read_screenshot("tasks/owned.jpg")
    response.close.assert_called_once()
    response.release_conn.assert_called_once()


async def test_failed_read_still_releases_connection(storage, minio):
    response = MagicMock()
    response.read.side_effect = TimeoutError("read stalled")
    minio.get_object.return_value = response
    with pytest.raises(TimeoutError):
        await storage.read_screenshot("tasks/owned.jpg")
    response.close.assert_called_once()
    response.release_conn.assert_called_once()
