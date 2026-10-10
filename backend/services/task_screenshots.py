"""Task artifact ownership and private, bounded S3 reads."""
from functools import lru_cache

import urllib3
from fastapi import HTTPException
from minio import Minio

from backend.core.config import settings
from backend.services.screenshot_storage import ScreenshotStorage


def task_screenshot_keys(task) -> list[str]:
    result = task.result if isinstance(task.result, dict) else {}
    logs = result.get("node_logs", [])
    keys = [log.get("screenshot_key") for log in logs if isinstance(log, dict)] if isinstance(logs, list) else []
    keys.append(result.get("final_screenshot_key"))
    return list(dict.fromkeys(key for key in keys if isinstance(key, str) and key))


def owned_screenshot_key(task, key: str) -> bool:
    prefix = f"tasks/{task.id}/{task.device_id}/"
    return (len(key) <= 1024 and key.startswith(prefix)
            and all(part and part not in (".", "..") for part in key.split("/"))
            and "\\" not in key and not any(ord(char) < 32 for char in key))


@lru_cache(maxsize=1)
def get_screenshot_storage() -> ScreenshotStorage:
    if not (settings.SCREENSHOT_STORAGE_ENDPOINT
            and settings.SCREENSHOT_STORAGE_ACCESS_KEY.get_secret_value()
            and settings.SCREENSHOT_STORAGE_SECRET_KEY.get_secret_value()):
        raise HTTPException(503, "Screenshot storage is not configured")
    client = Minio(
        settings.SCREENSHOT_STORAGE_ENDPOINT,
        access_key=settings.SCREENSHOT_STORAGE_ACCESS_KEY.get_secret_value(),
        secret_key=settings.SCREENSHOT_STORAGE_SECRET_KEY.get_secret_value(),
        secure=settings.SCREENSHOT_STORAGE_SECURE,
        region=settings.SCREENSHOT_STORAGE_REGION,
        http_client=urllib3.PoolManager(timeout=urllib3.Timeout(connect=1, read=3), retries=False),
    )
    return ScreenshotStorage(client)
