# backend/services/screenshot_storage.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-5. Хранение скриншотов в MinIO (локально) или S3 (production).
#
# MERGE — при интеграции с TZ-05 (H.264 streaming):
#   TZ-05 использует отдельный бинарный bucket для видеофреймов.
#   ScreenshotStorage работает с JPEG frames (не NAL units).
from __future__ import annotations

import asyncio
import io
import time
from datetime import timedelta

import structlog

logger = structlog.get_logger()

BUCKET = "sphere-screenshots"
SCREENSHOT_TTL_SECONDS = 3600   # Presigned URL TTL: 1 час
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024


class ScreenshotStorage:
    """
    Хранит JPEG скриншоты задач в MinIO/S3.
    Возвращает временные presigned URL (TTL 1 час).
    """

    def __init__(self, minio_client, presign_ttl: int = SCREENSHOT_TTL_SECONDS) -> None:
        self.client = minio_client
        self.presign_ttl = presign_ttl

    async def upload_screenshot(
        self,
        task_id: str,
        device_id: str,
        node_id: str,
        image_bytes: bytes,
    ) -> str:
        """
        Загрузить скриншот в MinIO.
        Путь: tasks/{task_id}/{device_id}/{node_id}/{timestamp}.jpg
        Возвращает ключ объекта (не URL — URL генерируется через presign).
        """
        key = f"tasks/{task_id}/{device_id}/{node_id}/{int(time.time())}.jpg"

        await asyncio.to_thread(
            self.client.put_object,
            BUCKET,
            key,
            io.BytesIO(image_bytes),
            len(image_bytes),
            content_type="image/jpeg",
        )
        logger.debug("screenshot.uploaded", key=key, size=len(image_bytes))
        return key

    async def get_presigned_url(self, key: str) -> str:
        """Получить временный URL для просмотра скриншота (TTL из presign_ttl)."""
        url = await asyncio.to_thread(
            self.client.presigned_get_object,
            BUCKET,
            key,
            expires=timedelta(seconds=self.presign_ttl),
        )
        return url

    async def read_screenshot(self, key: str) -> tuple[bytes, str]:
        """Bound memory and close the SDK response even on rejected content."""
        def read() -> tuple[bytes, str]:
            response = self.client.get_object(BUCKET, key)
            try:
                data = response.read(MAX_SCREENSHOT_BYTES + 1)
                if len(data) > MAX_SCREENSHOT_BYTES:
                    raise ValueError("Screenshot exceeds the 5 MiB limit")
                if data.startswith(b"\xff\xd8\xff"):
                    return data, "image/jpeg"
                if data.startswith(b"\x89PNG\r\n\x1a\n"):
                    return data, "image/png"
                raise ValueError("Stored screenshot is not a JPEG or PNG image")
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(read)

    async def delete_screenshot(self, key: str) -> None:
        """Удалить скриншот (например, при очистке старых задач)."""
        await asyncio.to_thread(self.client.remove_object, BUCKET, key)
