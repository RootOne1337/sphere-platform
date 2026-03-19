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
from sqlalchemy.orm import selectinload
from sqlalchemy import select

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
    """
    Creates a dispatch function that opens a fresh DB session for each
    dispatcher tick and closes it properly after dispatch completes.
    On startup, recovers orphaned task_running locks (task stuck after restart).
    """
    from backend.database.redis_client import redis as _redis
    from backend.database.redis_client import redis_binary as _redis_bin

    if _redis is None:
        return

    # Recovery: find task_running:* keys where DB task is still queued (not running)
    # This handles the case where backend restarted mid-dispatch
    try:
        running_keys = await _redis.keys("task_running:*")
        if running_keys:
            async with AsyncSessionLocal() as db:
                from backend.models.task import Task as _Task
                from backend.models.task import TaskStatus as _TS
                queue_tmp = TaskQueue(_redis)
                for key in running_keys:
                    key_str = key if isinstance(key, str) else key.decode()
                    task_id_bytes = await _redis.get(key_str)
                    if not task_id_bytes:
                        continue
                    task_id_str = task_id_bytes if isinstance(task_id_bytes, str) else task_id_bytes.decode()
                    device_id_str = key_str.removeprefix("task_running:")
                    try:
                        import uuid as _uuid
                        task = await db.get(_Task, _uuid.UUID(task_id_str))
                        if task and task.status in (_TS.QUEUED, _TS.ASSIGNED):
                            # Orphaned lock: task not actually running, requeue
                            await queue_tmp.mark_completed(task_id_str, device_id_str)
                            await queue_tmp.enqueue(
                                task_id_str, device_id_str, str(task.org_id), task.priority
                            )
                            logger.warning(
                                "task.orphaned_lock_recovered",
                                task_id=task_id_str,
                                device_id=device_id_str,
                            )
                    except Exception as exc:
                        logger.error("task.recovery_error", key=key_str, error=str(exc))
    except Exception as exc:
        logger.error("task.startup_recovery_failed", error=str(exc))

    async def _dispatch_once() -> None:
        from backend.database.redis_client import redis as _redis
        from backend.websocket.pubsub_router import get_pubsub_publisher
        async with AsyncSessionLocal() as db:
            queue = TaskQueue(_redis)
            cache = DeviceStatusCache(_redis_bin)
            publisher = get_pubsub_publisher()
            svc = TaskService(db, queue, status_cache=cache, publisher=publisher)
            await svc.dispatch_pending_tasks()
            await db.commit()

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
    redis=Depends(get_redis),
) -> dict:
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
    redis=Depends(get_redis),
) -> list[dict]:
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
)
async def force_stop_task(
    task_id: uuid.UUID,
    current_user: User = require_permission("script:execute"),
    svc: TaskService = Depends(get_task_service),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task = await svc.force_stop_task(task_id, current_user.org_id)
    await db.commit()
    return {"status": "stopped", "task_id": str(task.id)}
