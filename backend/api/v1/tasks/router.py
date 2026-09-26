# backend/api/v1/tasks/router.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-3+5. Tasks API + dispatcher startup registration.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
#
# ARCH-3: При импорте этого модуля register_startup регистрирует task_dispatcher_loop.
# main.py не нужно изменять — хук запускается автоматически.
from __future__ import annotations

import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.dependencies import require_permission
from backend.core.lifespan_registry import register_startup
from backend.database.engine import AsyncSessionLocal, get_db
from backend.database.redis_client import get_redis, get_redis_binary
from backend.models.task import Task, TaskStatus
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
    from backend.websocket.pubsub_router import get_pubsub_publisher
    status_cache = DeviceStatusCache(redis_bin)
    publisher = get_pubsub_publisher()
    return TaskService(db, queue, status_cache=status_cache, publisher=publisher)


# ── Startup: запустить диспетчер задач ───────────────────────────────────────

async def _startup_dispatcher() -> None:
    """Always register; resolve current dependencies on every recovery tick."""
    from backend.services.task_dispatcher import TaskDispatchWorker

    worker = TaskDispatchWorker(AsyncSessionLocal)

    async def _dispatch_once() -> None:
        from backend.database.redis_client import redis_binary
        from backend.websocket.pubsub_router import get_pubsub_publisher

        await worker.poll(
            status_cache=DeviceStatusCache(redis_binary) if redis_binary is not None else None,
            publisher=get_pubsub_publisher(),
        )

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
    search: str = Query("", max_length=200),
    sort_by: Literal["created_at", "status", "script_name", "priority"] = "created_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    active_only: bool = False,
    include_counts: bool = False,
    current_user: User = require_permission("script:read"),
    svc: TaskService = Depends(get_task_service),
) -> TaskListResponse:
    tasks, total, counts = await svc.list_tasks(
        org_id=current_user.org_id,
        device_id=device_id,
        script_id=script_id,
        status=status,
        batch_id=batch_id,
        page=page,
        per_page=per_page,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        active_only=active_only,
        include_counts=include_counts,
    )
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return TaskListResponse(
        items=[TaskResponse.model_validate(t) for t in tasks],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        status_counts=counts,
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
        account_id=body.account_id,
    )
    await db.commit()
    # Перезагрузить с relationships для сериализации (device_name, script_name)
    stmt = (
        select(Task)
        .options(selectinload(Task.device), selectinload(Task.script))
        .where(Task.id == task.id)
    )
    task = (await db.execute(stmt)).scalar_one()
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


# ── Live Progress ─────────────────────────────────────────────────────────────

@router.get(
    "/{task_id}/progress",
    summary="Live-прогресс выполнения задачи (из Redis кэша)",
)
async def get_task_progress(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> dict:
    if await db.scalar(select(Task.id).where(
        Task.id == task_id, Task.org_id == current_user.org_id,
    )) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    data = await redis.hgetall(f"task_progress:{task_id}")
    if not data:
        return {"nodes_done": 0, "total_nodes": 0, "current_node": "", "progress": 0, "cycles": 0, "started_at": None}
    return {
        "nodes_done": int(data.get("nodes_done", 0)),
        "total_nodes": int(data.get("total_nodes", 0)),
        "current_node": data.get("current_node", ""),
        "progress": int(data.get("progress", 0)),
        "cycles": int(data.get("cycles", 0)),
        "started_at": float(data["started_at"]) if data.get("started_at") else None,
    }


# ── Live Logs (running task) ─────────────────────────────────────────────────

@router.get(
    "/{task_id}/live-logs",
    summary="Live node execution log entries (from Redis, for running tasks)",
)
async def get_task_live_logs(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:read"),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
) -> list[dict]:
    if await db.scalar(select(Task.id).where(
        Task.id == task_id, Task.org_id == current_user.org_id,
    )) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    import json as _json
    entries = await redis.lrange(f"task_progress_log:{task_id}", 0, -1)
    if not entries:
        return []
    return [_json.loads(e) for e in entries]


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


# ── Force Stop (running task) ─────────────────────────────────────────────────

@router.post(
    "/{task_id}/stop",
    status_code=200,
    summary="Принудительно остановить задачу (QUEUED/ASSIGNED/RUNNING)",
    responses={202: {"description": "Cancellation persisted; waiting for the device's terminal result"}},
)
async def force_stop_task(
    task_id: uuid.UUID,
    response: Response,
    current_user: User = require_permission("script:execute"),
    svc: TaskService = Depends(get_task_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await svc.force_stop_task(task_id, current_user.org_id)
    await db.commit()
    stopped = task.status == TaskStatus.CANCELLED
    response.status_code = 200 if stopped else 202
    return {"status": "stopped" if stopped else "cancelling", "task_id": str(task.id)}
