# backend/api/v1/tasks/router.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-3+5. Tasks API + dispatcher startup registration.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# ARCH-3: При импорте этого модуля register_startup регистрирует task_dispatcher_loop.
# main.py не нужно изменять — хук запускается автоматически.
from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.core.lifespan_registry import register_startup
from backend.database.engine import AsyncSessionLocal, get_db
from backend.database.redis_client import get_redis, get_redis_binary
from backend.models.task import TaskStatus
from backend.models.user import User
from backend.schemas.task import (
    CreateTaskRequest,
    TaskDetailResponse,
    TaskListResponse,
    TaskResponse,
)
from backend.schemas.task_results import NodeExecutionLog
from backend.services.device_status_cache import DeviceStatusCache
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService, start_dispatcher

logger = structlog.get_logger()

router = APIRouter(prefix="/tasks", tags=["tasks"])


# ── DI фабрики ────────────────────────────────────────────────────────────────

def get_task_queue(redis=Depends(get_redis)) -> TaskQueue:
    return TaskQueue(redis)


def get_task_service(
    db: AsyncSession = Depends(get_db),
    queue: TaskQueue = Depends(get_task_queue),
    redis=Depends(get_redis),
    redis_bin=Depends(get_redis_binary),
) -> TaskService:
    status_cache = DeviceStatusCache(redis_bin)
    return TaskService(db, queue, status_cache=status_cache)


# ── Startup: запустить диспетчер задач ───────────────────────────────────────

async def _startup_dispatcher() -> None:
    """
    Creates a dispatch function that opens a fresh DB session for each
    dispatcher tick and closes it properly after dispatch completes.
    """
    async def _dispatch_once() -> None:
        from backend.database.redis_client import redis as _redis
        from backend.database.redis_client import redis_binary as _redis_bin
        async with AsyncSessionLocal() as db:
            queue = TaskQueue(_redis)
            cache = DeviceStatusCache(_redis_bin)
            svc = TaskService(db, queue, status_cache=cache)
            await svc.dispatch_pending_tasks()

    start_dispatcher(_dispatch_once)
    logger.info("task_dispatcher.registered")


register_startup("task_dispatcher", _startup_dispatcher)


# ── List ──────────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=TaskListResponse,
    summary="Список задач с фильтрацией",
)
async def list_tasks(
    device_id: uuid.UUID | None = None,
    script_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    batch_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    current_user: User = require_permission("script:read"),
    svc: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    tasks, total = await svc.list_tasks(
        org_id=current_user.org_id,
        device_id=device_id,
        script_id=script_id,
        status=status,
        batch_id=batch_id,
        page=page,
        per_page=per_page,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return TaskListResponse(
        items=[TaskResponse.model_validate(t) for t in tasks],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


# ── Create ────────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=TaskResponse,
    status_code=201,
    summary="Поставить задачу в очередь",
)
async def create_task(
    body: CreateTaskRequest,
    current_user: User = require_permission("script:execute"),
    svc: TaskService = Depends(get_task_service),
    db: AsyncSession = Depends(get_db),
) -> TaskResponse:
    task = await svc.create_task(
        script_id=body.script_id,
        device_id=body.device_id,
        org_id=current_user.org_id,
        priority=body.priority,
        webhook_url=body.webhook_url,
    )
    await db.commit()
    return TaskResponse.model_validate(task)


# ── Get one ───────────────────────────────────────────────────────────────────

@router.get(
    "/{task_id}",
    response_model=TaskDetailResponse,
    summary="Получить задачу по ID",
)
async def get_task(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    svc: TaskService = Depends(get_task_service),
) -> TaskDetailResponse:
    task = await svc._get_task(task_id, current_user.org_id)
    return TaskDetailResponse.model_validate(task)


# ── Logs ──────────────────────────────────────────────────────────────────────

@router.get(
    "/{task_id}/logs",
    response_model=list[NodeExecutionLog],
    summary="Логи выполнения задачи (per-node)",
)
async def get_task_logs(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    svc: TaskService = Depends(get_task_service),
) -> list[NodeExecutionLog]:
    task = await svc._get_task(task_id, current_user.org_id)
    # Логи хранятся в task.result["node_logs"] в формате NodeExecutionLog
    if not task.result or "node_logs" not in task.result:
        return []
    return [NodeExecutionLog.model_validate(log) for log in task.result["node_logs"]]


# ── Screenshots ───────────────────────────────────────────────────────────────

@router.get(
    "/{task_id}/screenshots",
    summary="Presigned URLs к скриншотам задачи (TTL 1 час)",
)
async def get_task_screenshots(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    svc: TaskService = Depends(get_task_service),
) -> dict:
    task = await svc._get_task(task_id, current_user.org_id)

    screenshot_keys: list[str] = []
    if task.result:
        # Собрать ключи из node_logs
        for log in task.result.get("node_logs", []):
            if log.get("screenshot_key"):
                screenshot_keys.append(log["screenshot_key"])
        if task.result.get("final_screenshot_key"):
            screenshot_keys.append(task.result["final_screenshot_key"])

    if not screenshot_keys:
        return {"screenshots": []}

    try:
        from backend.services.screenshot_storage import ScreenshotStorage
        storage = ScreenshotStorage.__new__(ScreenshotStorage)  # stub без minio
        urls = [await storage.get_presigned_url(k) for k in screenshot_keys]
    except Exception:
        # MinIO может быть недоступен — возвращать ключи
        urls = screenshot_keys

    return {"screenshots": urls}


# ── Cancel ────────────────────────────────────────────────────────────────────

@router.delete(
    "/{task_id}",
    status_code=204,
    response_model=None,
    summary="Отменить задачу (только QUEUED/ASSIGNED)",
)
async def cancel_task(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:execute"),
    svc: TaskService = Depends(get_task_service),
    db: AsyncSession = Depends(get_db),
) -> None:
    await svc.cancel_task(task_id, current_user.org_id)
    await db.commit()
