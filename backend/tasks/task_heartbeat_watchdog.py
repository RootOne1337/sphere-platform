# backend/tasks/task_heartbeat_watchdog.py
# ВЛАДЕЛЕЦ: TZ-04 WATCHDOG. Heartbeat watchdog для зависших задач.
#
# ПРОБЛЕМА:
#   Задача успешно создаётся планировщиком и попадает в очередь Redis.
#   Диспетчер отправляет EXECUTE_DAG агенту и ставит Redis lock:
#       task_running:{device_id}  TTL=3600s
#   Если агент отключается до отправки command_result — lock остаётся.
#   Следствие: следующие тики планировщика создают задачи, но dispatch
#   блокируется "мёртвым" lock-ом. Устройство недоступно весь TTL (1 час).
#
# РЕШЕНИЕ:
#   Watchdog каждые 60с находит задачи в RUNNING/QUEUED/ASSIGNED, которые
#   превысили допустимое время выполнения. Переводит в TIMEOUT, агрегирует
#   batch, а затем освобождает Redis lock — устройство снова принимает задачи.
#
#   Порядок операций намеренно: сначала БД commit, потом Redis DELETE.
#   Это гарантирует консистентность: если Redis операция упадёт — задача в БД
#   уже TIMEOUT, watchdog попытается снова на следующем цикле (lock сам
#   истечёт через max(TTL, 3600s)).
#
# КОНФИГУРАЦИЯ (переопределяется через env):
#   TASK_STALE_BUFFER_SECONDS=300  — буфер сверх task.timeout_seconds для RUNNING
#   TASK_QUEUED_STALE_MINUTES=60   — таймаут для QUEUED задач без started_at
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from backend.core.lifespan_registry import register_shutdown, register_startup
from backend.database.engine import AsyncSessionLocal

logger = structlog.get_logger()

# ── Конфигурация ─────────────────────────────────────────────────────────────

# Дополнительный буфер (сек) сверх task.timeout_seconds для RUNNING задач.
# task.timeout_seconds=300 (5 мин) → stale threshold = 300+300 = 600с (10 мин).
# Задачи планировщика (перезапуск скрипта) должны укладываться в <5 мин — 10 мин запас.
_STALE_BUFFER_SECONDS: int = int(os.environ.get("TASK_STALE_BUFFER_SECONDS", "300"))

# Абсолютный таймаут для QUEUED/ASSIGNED задач без started_at.
# После этого порога задача переводится в TIMEOUT и удаляется из Redis ZSet.
_QUEUED_STALE_MINUTES: int = int(os.environ.get("TASK_QUEUED_STALE_MINUTES", "60"))

# Интервал watchdog цикла в секундах.
_WATCHDOG_INTERVAL_SECONDS: int = 60

# Ссылка на asyncio.Task — защита от garbage collector.
_watchdog_task: asyncio.Task | None = None


# ── Основная логика ──────────────────────────────────────────────────────────

async def _process_stale_tasks(
    db,
    *,
    stale_buffer_seconds: int,
    queued_stale_minutes: int,
    use_for_update: bool = True,
) -> tuple[list[tuple[str, str]], list[tuple[str, str, str]]]:
    """
    Ядро watchdog: находит зависшие задачи, переводит в TIMEOUT, агрегирует batch.

    Возвращает:
        expired_running — [(task_id, device_id)] для освобождения Redis lock
        expired_queued  — [(task_id, device_id, org_id)] для удаления из ZSet

    Commit НЕ делает — ответственность на вызывающей стороне.
    Параметр use_for_update=False — для тестов на SQLite (не поддерживает SKIP LOCKED).

    RUNNING задача зависла если:
        started_at + timeout_seconds + stale_buffer_seconds < NOW()

    QUEUED / ASSIGNED задача зависла если:
        created_at + queued_stale_minutes < NOW()
    """
    from backend.models.task import Task, TaskStatus
    from backend.models.task_batch import TaskBatch, TaskBatchStatus

    now = datetime.now(timezone.utc)
    queued_cutoff = now - timedelta(minutes=queued_stale_minutes)
    # Для SQLite (тесты) используем naive datetime в WHERE — PostgreSQL принимает оба варианта.
    queued_cutoff_naive = queued_cutoff.replace(tzinfo=None)

    expired_running: list[tuple[str, str]] = []   # [(task_id, device_id)]
    expired_queued: list[tuple[str, str, str]] = []  # [(task_id, device_id, org_id)]

    # ── 1. RUNNING задачи: превысили timeout + buffer ─────────────────────────
    running_q = (
        select(Task)
        .where(
            Task.status == TaskStatus.RUNNING,
            Task.started_at.is_not(None),
        )
    )
    if use_for_update:
        # FOR UPDATE SKIP LOCKED: безопасно при нескольких инстансах бэкенда
        running_q = running_q.with_for_update(skip_locked=True)

    running_stale: list[Task] = list((await db.scalars(running_q)).all())

    for task in running_stale:
        if task.started_at is None:
            continue  # Защита от некорректных данных: started_at должен быть set
        # SQLite возвращает naive datetime — нормализуем в UTC для сравнения
        started_at = task.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        stale_after = started_at + timedelta(
            seconds=task.timeout_seconds + stale_buffer_seconds
        )
        if now < stale_after:
            continue  # Ещё в пределах допустимого — не трогаем

        task.status = TaskStatus.TIMEOUT
        task.finished_at = now
        task.error_message = (
            f"Watchdog: задача не завершилась за "
            f"{task.timeout_seconds + stale_buffer_seconds}с "
            f"(timeout={task.timeout_seconds}s + буфер={stale_buffer_seconds}s). "
            f"Агент вероятно отключился не отправив command_result."
        )
        expired_running.append((str(task.id), str(task.device_id)))

        logger.warning(
            "task.watchdog.running_timeout",
            task_id=str(task.id),
            device_id=str(task.device_id),
            started_at=task.started_at.isoformat(),
            timeout_seconds=task.timeout_seconds,
            stale_after=stale_after.isoformat(),
        )

    # ── 2. QUEUED / ASSIGNED задачи: зависли в очереди ───────────────────────
    queued_q = (
        select(Task)
        .where(
            Task.status.in_([TaskStatus.QUEUED, TaskStatus.ASSIGNED]),
            Task.created_at < queued_cutoff_naive,
        )
    )
    if use_for_update:
        queued_q = queued_q.with_for_update(skip_locked=True)

    queued_stale: list[Task] = list((await db.scalars(queued_q)).all())

    for task in queued_stale:
        task.status = TaskStatus.TIMEOUT
        task.finished_at = now
        task.error_message = (
            f"Watchdog: провела >{queued_stale_minutes} мин "
            f"в очереди без выполнения. "
            f"Устройство недоступно или диспетчер не смог доставить задачу."
        )
        # SQLite возвращает naive datetime — нормализуем для вычисления age_min
        created_at = task.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_min = round((now - created_at).total_seconds() / 60, 1) if created_at else 0
        expired_queued.append((str(task.id), str(task.device_id), str(task.org_id)))

        logger.warning(
            "task.watchdog.queued_timeout",
            task_id=str(task.id),
            device_id=str(task.device_id),
            age_minutes=age_min,
        )

    # ── 3. Batch агрегация ────────────────────────────────────────────────────
    all_timed = [t for t in running_stale + queued_stale if t.status == TaskStatus.TIMEOUT]
    if all_timed:
        await _aggregate_batches(db, all_timed, now, TaskBatch, TaskBatchStatus)

    total_expired = len(expired_running) + len(expired_queued)
    if total_expired:
        logger.info(
            "task.watchdog.cycle_done",
            running_expired=len(expired_running),
            queued_expired=len(expired_queued),
            total=total_expired,
        )

    return expired_running, expired_queued


async def _expire_stale_tasks() -> None:
    """
    Один цикл watchdog: создаёт сессию, вызывает ядро, применяет Redis-операции.

    RUNNING задача зависла если:
        started_at + timeout_seconds + STALE_BUFFER_SECONDS < NOW()

    QUEUED / ASSIGNED задача зависла если:
        created_at + QUEUED_STALE_MINUTES < NOW()

    Для каждой зависшей задачи:
      1. Статус → TIMEOUT, finished_at = NOW()
      2. Обновляем счётчики TaskBatch.failed
      3. После db.commit() освобождаем Redis lock (только для RUNNING)
         или удаляем из ZSet (только для QUEUED/ASSIGNED)
    """
    # Инициализируем Redis-зависимости внутри функции — избегаем module-level import
    # на случай если Redis ещё не запущен при старте.
    try:
        from backend.database.redis_client import redis_binary
        from backend.services.task_queue import TaskQueue

        queue: TaskQueue | None = TaskQueue(redis_binary) if redis_binary else None
    except Exception:
        queue = None

    expired_running: list[tuple[str, str]] = []
    expired_queued: list[tuple[str, str, str]] = []

    async with AsyncSessionLocal() as db:
        try:
            expired_running, expired_queued = await _process_stale_tasks(
                db,
                stale_buffer_seconds=_STALE_BUFFER_SECONDS,
                queued_stale_minutes=_QUEUED_STALE_MINUTES,
                use_for_update=True,
            )

            if expired_running or expired_queued:
                await db.commit()

        except Exception as exc:
            logger.error("task.watchdog.tick_error", error=str(exc), exc_info=True)
            await db.rollback()
            # Очищаем списки чтобы не пытаться освободить lock при ошибке
            expired_running.clear()
            expired_queued.clear()

    # ── 4. Redis операции ПОСЛЕ db.commit() ──────────────────────────────────
    # Порядок намеренный: БД — источник истины. Сначала commit, потом Redis.
    if queue:
        # RUNNING: освободить running lock + отправить CANCEL_DAG устройству
        for task_id, device_id in expired_running:
            try:
                await queue.mark_completed(task_id, device_id)
                logger.debug(
                    "task.watchdog.lock_released",
                    task_id=task_id,
                    device_id=device_id,
                )
            except Exception as exc:
                logger.error(
                    "task.watchdog.lock_release_error",
                    task_id=task_id,
                    device_id=device_id,
                    error=str(exc),
                )
            # FIX: Отправляем CANCEL_DAG устройству чтобы остановить зацикленный DAG.
            # Без этого: watchdog освобождал Redis lock, но на устройстве DAG продолжал
            # крутиться → dagMutex заблокирован → новая задача не запустится.
            try:
                from backend.websocket.pubsub_router import get_pubsub_publisher
                pub = get_pubsub_publisher()
                if pub:
                    import time as _time
                    await pub.send_command_live(
                        device_id,
                        {
                            "type": "CANCEL_DAG",
                            "command_id": f"watchdog_cancel_{task_id}",
                            "signed_at": int(_time.time()),
                            "ttl_seconds": 30,
                        },
                    )
                    logger.info(
                        "task.watchdog.cancel_dag_sent",
                        task_id=task_id,
                        device_id=device_id,
                    )
            except Exception as exc:
                logger.warning(
                    "task.watchdog.cancel_dag_failed",
                    task_id=task_id,
                    device_id=device_id,
                    error=str(exc),
                )

        # QUEUED: удалить из ZSet → не будет диспетчеризована позднее
        for task_id, device_id, org_id in expired_queued:
            try:
                await queue.cancel_task(task_id, org_id, device_id)
                logger.debug(
                    "task.watchdog.queued_removed_from_zset",
                    task_id=task_id,
                    device_id=device_id,
                )
            except Exception as exc:
                logger.error(
                    "task.watchdog.queued_cancel_error",
                    task_id=task_id,
                    device_id=device_id,
                    error=str(exc),
                )


async def _aggregate_batches(
    db,
    timed_tasks,
    now: datetime,
    TaskBatch,
    TaskBatchStatus,
) -> None:
    """
    Инкрементально обновить счётчики TaskBatch для тайм-аутовавших задач.

    Группируем по batch_id, считаем количество TIMEOUT-задач в каждом batch
    и обновляем batch.failed. Если все задачи batch завершены — вычисляем
    финальный статус (FAILED / COMPLETED / PARTIAL).
    """
    # Собираем уникальные batch_id
    batch_ids_counts: dict = {}  # batch_id → count of timed-out tasks
    for task in timed_tasks:
        if task.batch_id:
            batch_ids_counts[task.batch_id] = batch_ids_counts.get(task.batch_id, 0) + 1

    for batch_id, timeout_count in batch_ids_counts.items():
        batch = await db.get(TaskBatch, batch_id)
        if not batch:
            continue

        batch.failed = (batch.failed or 0) + timeout_count
        completed_count = (batch.succeeded or 0) + (batch.failed or 0)

        if completed_count >= batch.total:
            if (batch.failed or 0) == 0:
                batch.status = TaskBatchStatus.COMPLETED
            elif (batch.succeeded or 0) == 0:
                batch.status = TaskBatchStatus.FAILED
            else:
                batch.status = TaskBatchStatus.PARTIAL

            logger.info(
                "task.watchdog.batch_finalized",
                batch_id=str(batch_id),
                status=batch.status,
                succeeded=batch.succeeded,
                failed=batch.failed,
                total=batch.total,
            )


# ── Watchdog loop ────────────────────────────────────────────────────────────

async def _watchdog_loop() -> None:
    """Бесконечный цикл watchdog с паузой _WATCHDOG_INTERVAL_SECONDS."""
    logger.info(
        "task_heartbeat_watchdog.started",
        interval_s=_WATCHDOG_INTERVAL_SECONDS,
        stale_buffer_s=_STALE_BUFFER_SECONDS,
        queued_stale_m=_QUEUED_STALE_MINUTES,
    )
    while True:
        try:
            await _expire_stale_tasks()
        except Exception as exc:
            logger.error(
                "task_heartbeat_watchdog.unhandled_error",
                error=str(exc),
                exc_info=True,
            )
        await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)


# ── Авторегистрация через lifespan_registry ──────────────────────────────────

async def _startup() -> None:
    """Запуск watchdog при старте FastAPI."""
    global _watchdog_task
    _watchdog_task = asyncio.create_task(
        _watchdog_loop(),
        name="task_heartbeat_watchdog",
    )
    logger.info(
        "task_heartbeat_watchdog.registered",
        stale_buffer_s=_STALE_BUFFER_SECONDS,
        queued_stale_m=_QUEUED_STALE_MINUTES,
    )


async def _shutdown() -> None:
    """Graceful shutdown watchdog при остановке FastAPI."""
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass
    logger.info("task_heartbeat_watchdog.stopped")


register_startup("task_heartbeat_watchdog", _startup)
register_shutdown("task_heartbeat_watchdog", _shutdown)
