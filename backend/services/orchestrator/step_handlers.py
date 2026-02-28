# backend/services/orchestrator/step_handlers.py
# ВЛАДЕЛЕЦ: TZ-12 SPLIT-4. Обработчики шагов pipeline.
#
# Каждый StepType имеет свой handler, который:
# 1. Получает step (dict из steps_snapshot) + PipelineRun + db session
# 2. Исполняет логику
# 3. Возвращает StepResult (status, output, error, context_updates)
#
# Система расширяема: для нового типа шага достаточно зарегистрировать handler.
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.pipeline import PipelineRun
from backend.models.task import Task, TaskStatus

logger = structlog.get_logger()


@dataclass
class StepResult:
    """Результат исполнения шага."""
    status: str = "success"           # "success" | "failure"
    output: dict[str, Any] | None = None
    error: str | None = None
    context_updates: dict[str, Any] = field(default_factory=dict)


# Тип обработчика шага
StepHandler = Callable[
    [dict[str, Any], PipelineRun, AsyncSession],
    Awaitable[StepResult],
]


class StepHandlerRegistry:
    """
    Реестр обработчиков шагов.

    Автоматически выбирает handler по step["type"].
    Поддерживает расширение через register().
    """
    _handlers: dict[str, StepHandler] = {}

    @classmethod
    def register(cls, step_type: str, handler: StepHandler) -> None:
        """Зарегистрировать обработчик для типа шага."""
        cls._handlers[step_type] = handler

    @classmethod
    async def execute(
        cls,
        step: dict[str, Any],
        run: PipelineRun,
        db: AsyncSession,
    ) -> StepResult:
        """Исполнить шаг через соответствующий handler."""
        step_type = step.get("type", "")
        handler = cls._handlers.get(step_type)
        if not handler:
            return StepResult(
                status="failure",
                error=f"Неизвестный тип шага: {step_type}",
            )

        timeout_ms = step.get("timeout_ms", 60_000)
        try:
            return await asyncio.wait_for(
                handler(step, run, db),
                timeout=timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            return StepResult(
                status="failure",
                error=f"Таймаут шага: {timeout_ms}ms",
            )
        except Exception as exc:
            logger.error(
                "step_handler.error",
                step_type=step_type,
                step_id=step.get("id"),
                error=str(exc),
            )
            return StepResult(status="failure", error=str(exc))


# ══════════════════════════════════════════════════════════════════════════════
#  Конкретные обработчики шагов
# ══════════════════════════════════════════════════════════════════════════════


async def handle_execute_script(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг execute_script — запуск DAG-скрипта на устройстве.

    params:
      - script_id: UUID скрипта
      - priority: приоритет (default 5)

    Создаёт Task, ожидает его завершения (polling), возвращает результат.
    """
    params = step.get("params", {})
    script_id_str = params.get("script_id")
    if not script_id_str:
        return StepResult(status="failure", error="script_id не указан в params")

    try:
        script_id = uuid.UUID(script_id_str)
    except (ValueError, TypeError):
        return StepResult(status="failure", error=f"Некорректный script_id: {script_id_str}")

    priority = params.get("priority", 5)

    # Создать задачу
    from backend.models.script import Script, ScriptVersion
    script = await db.scalar(
        select(Script).where(Script.id == script_id, Script.org_id == run.org_id)
    )
    if not script:
        return StepResult(status="failure", error=f"Скрипт {script_id_str} не найден")

    # Найти версию скрипта
    version = await db.scalar(
        select(ScriptVersion)
        .where(ScriptVersion.script_id == script_id)
        .order_by(ScriptVersion.version.desc())
        .limit(1)
    )

    task = Task(
        org_id=run.org_id,
        script_id=script_id,
        device_id=run.device_id,
        script_version_id=version.id if version else None,
        status=TaskStatus.QUEUED,
        priority=priority,
        input_params=run.context.get("_input_overrides", run.input_params),
    )
    db.add(task)
    await db.flush()

    # Привязать task к run
    run.current_task_id = task.id
    await db.commit()

    logger.info(
        "step.execute_script.task_created",
        step_id=step.get("id"),
        task_id=str(task.id),
        script_id=script_id_str,
    )

    # Polling: ожидаем завершения task (с таймаутом шага = timeout_ms)
    poll_interval = 1.0  # секунда
    while True:
        await asyncio.sleep(poll_interval)
        await db.refresh(task)

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED):
            break

    # Снять привязку
    run.current_task_id = None
    await db.commit()

    if task.status == TaskStatus.COMPLETED:
        return StepResult(
            status="success",
            output=task.result or {},
            context_updates={"last_task_id": str(task.id), "last_task_result": task.result or {}},
        )
    else:
        return StepResult(
            status="failure",
            error=task.error_message or f"Task завершился со статусом {task.status}",
            output=task.result,
        )


async def handle_condition(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг condition — условный переход.

    params:
      - expression: строка-выражение (операторы ==, !=, >, <, in)
      - context_key: ключ в context для проверки
      - expected_value: ожидаемое значение
      - operator: "eq" | "neq" | "gt" | "lt" | "in" | "not_in" | "exists"
      - on_true: step_id при истине (переопределяет on_success)
      - on_false: step_id при ложи (переопределяет on_failure)
    """
    params = step.get("params", {})
    context_key = params.get("context_key", "")
    operator = params.get("operator", "eq")
    expected = params.get("expected_value")

    actual = run.context.get(context_key)

    result = _evaluate_condition(actual, operator, expected)

    # Переопределяем on_success/on_failure через on_true/on_false
    context_updates: dict[str, Any] = {"_condition_result": result}

    if result:
        on_true = params.get("on_true")
        if on_true:
            context_updates["_next_step_override"] = on_true
        return StepResult(status="success", output={"condition": True}, context_updates=context_updates)
    else:
        on_false = params.get("on_false")
        if on_false:
            # Используем failure чтобы перейти к on_failure (= on_false шаг)
            # Но лучше подменить on_success — зависит от архитектуры
            # В нашем движке: success → on_success, failure → on_failure
            # Для on_false → ставим failure + переопределяем on_failure в step
            pass
        return StepResult(status="failure", output={"condition": False}, context_updates=context_updates)


async def handle_action(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг action — отправка команды на устройство через WebSocket.

    params:
      - command: тип команды (reboot, clear_data, install_apk, ...)
      - payload: дополнительные данные
    """
    params = step.get("params", {})
    command = params.get("command")
    payload = params.get("payload", {})

    if not command:
        return StepResult(status="failure", error="command не указан в params")

    # Отправка через Redis PubSub → WebSocket → агент
    try:
        from backend.database.redis_client import redis as _redis
        if _redis:
            import json
            message = json.dumps({
                "type": "command",
                "command": command,
                "device_id": str(run.device_id),
                "payload": payload,
                "pipeline_run_id": str(run.id),
            })
            await _redis.publish(f"device:{run.device_id}:commands", message)

        logger.info(
            "step.action.sent",
            step_id=step.get("id"),
            command=command,
            device_id=str(run.device_id),
        )
        return StepResult(
            status="success",
            output={"command": command, "sent": True},
        )
    except Exception as exc:
        return StepResult(status="failure", error=f"Ошибка отправки команды: {exc}")


async def handle_delay(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг delay — задержка на N миллисекунд.

    params:
      - delay_ms: длительность задержки (мс)
    """
    params = step.get("params", {})
    delay_ms = params.get("delay_ms", 1000)
    delay_ms = max(100, min(delay_ms, 300_000))  # 100ms..5min

    await asyncio.sleep(delay_ms / 1000.0)
    return StepResult(
        status="success",
        output={"delayed_ms": delay_ms},
    )


async def handle_wait_for_event(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг wait_for_event — ожидание события от устройства через Redis PubSub.

    params:
      - event_type: тип ожидаемого события
      - timeout_ms: таймаут (используется из step.timeout_ms)
    """
    params = step.get("params", {})
    event_type = params.get("event_type")

    if not event_type:
        return StepResult(status="failure", error="event_type не указан")

    # Подписка на Redis канал событий устройства
    try:
        from backend.database.redis_client import redis as _redis
        if not _redis:
            return StepResult(status="failure", error="Redis недоступен")

        channel = f"device:{run.device_id}:events"
        pubsub = _redis.pubsub()
        await pubsub.subscribe(channel)

        try:
            timeout_sec = step.get("timeout_ms", 60_000) / 1000.0
            end_time = asyncio.get_event_loop().time() + timeout_sec

            while asyncio.get_event_loop().time() < end_time:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message and message["type"] == "message":
                    import json
                    try:
                        data = json.loads(message["data"])
                        if data.get("event_type") == event_type:
                            return StepResult(
                                status="success",
                                output={"event": data},
                                context_updates={"last_event": data},
                            )
                    except (json.JSONDecodeError, TypeError):
                        continue

            return StepResult(
                status="failure",
                error=f"Таймаут ожидания события {event_type}",
            )
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
    except Exception as exc:
        return StepResult(status="failure", error=f"Ошибка ожидания события: {exc}")


async def handle_parallel(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг parallel — параллельное исполнение подшагов.

    params:
      - sub_steps: список шагов-id для параллельного исполнения
      - mode: "all" (все должны succeed) | "any" (хотя бы один)

    Ограничение: параллельные подшаги — только простые (action, delay).
    execute_script в параллели не поддерживается (один device = один task).
    """
    params = step.get("params", {})
    sub_step_ids = params.get("sub_steps", [])
    mode = params.get("mode", "all")

    if not sub_step_ids:
        return StepResult(status="success", output={"parallel": []})

    # Извлечь подшаги из steps_snapshot
    step_index = {s["id"]: s for s in (run.steps_snapshot or [])}
    sub_steps = [step_index[sid] for sid in sub_step_ids if sid in step_index]

    if not sub_steps:
        return StepResult(status="failure", error="Подшаги не найдены в steps_snapshot")

    # Параллельное исполнение
    tasks = [
        StepHandlerRegistry.execute(step=ss, run=run, db=db)
        for ss in sub_steps
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    outputs = []
    successes = 0
    failures = 0
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            failures += 1
            outputs.append({"step_id": sub_step_ids[i], "status": "failure", "error": str(res)})
        else:
            outputs.append({"step_id": sub_step_ids[i], "status": res.status, "output": res.output})
            if res.status == "success":
                successes += 1
            else:
                failures += 1

    if mode == "all" and failures > 0:
        return StepResult(
            status="failure",
            output={"parallel": outputs, "successes": successes, "failures": failures},
            error=f"{failures} подшаг(ов) завершились ошибкой",
        )

    return StepResult(
        status="success",
        output={"parallel": outputs, "successes": successes, "failures": failures},
    )


async def handle_loop(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг loop — цикличное исполнение подшага N раз.

    params:
      - iterations: количество итераций
      - sub_step_id: ID шага для повтора
      - break_on_failure: остановить цикл при ошибке (default: true)
    """
    params = step.get("params", {})
    iterations = min(params.get("iterations", 1), 1000)
    sub_step_id = params.get("sub_step_id")
    break_on_failure = params.get("break_on_failure", True)

    if not sub_step_id:
        return StepResult(status="failure", error="sub_step_id не указан")

    step_index = {s["id"]: s for s in (run.steps_snapshot or [])}
    sub_step = step_index.get(sub_step_id)
    if not sub_step:
        return StepResult(status="failure", error=f"Подшаг {sub_step_id} не найден")

    results = []
    for i in range(iterations):
        # Обновить iteration counter в контексте
        ctx = dict(run.context)
        ctx["_loop_iteration"] = i
        run.context = ctx
        await db.commit()

        res = await StepHandlerRegistry.execute(step=sub_step, run=run, db=db)
        results.append({"iteration": i, "status": res.status})

        if res.status == "failure" and break_on_failure:
            return StepResult(
                status="failure",
                output={"loop": results, "stopped_at": i},
                error=res.error or f"Итерация {i} завершилась ошибкой",
            )

    return StepResult(
        status="success",
        output={"loop": results, "total_iterations": iterations},
    )


async def handle_n8n_workflow(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг n8n_workflow — вызов внешнего n8n webhook.

    params:
      - webhook_url: URL n8n webhook
      - payload: данные для отправки (шаблонизируются из context)
    """
    params = step.get("params", {})
    webhook_url = params.get("webhook_url")
    payload = params.get("payload", {})

    if not webhook_url:
        return StepResult(status="failure", error="webhook_url не указан")

    # Подставить переменные из контекста
    enriched_payload = {
        **payload,
        "pipeline_run_id": str(run.id),
        "device_id": str(run.device_id),
        "context": run.context,
    }

    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json=enriched_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status < 400:
                    body = await resp.json()
                    return StepResult(
                        status="success",
                        output={"status_code": resp.status, "body": body},
                        context_updates={"n8n_response": body},
                    )
                else:
                    text = await resp.text()
                    return StepResult(
                        status="failure",
                        error=f"n8n webhook вернул {resp.status}: {text[:500]}",
                    )
    except Exception as exc:
        return StepResult(status="failure", error=f"Ошибка вызова n8n: {exc}")


async def handle_sub_pipeline(
    step: dict[str, Any],
    run: PipelineRun,
    db: AsyncSession,
) -> StepResult:
    """
    Шаг sub_pipeline — запуск вложенного pipeline.

    params:
      - pipeline_id: UUID вложенного pipeline
      - input_params: параметры для вложенного (можно ссылаться на context)
    """
    params = step.get("params", {})
    pipeline_id_str = params.get("pipeline_id")
    sub_input = params.get("input_params", {})

    if not pipeline_id_str:
        return StepResult(status="failure", error="pipeline_id не указан")

    try:
        pipeline_id = uuid.UUID(pipeline_id_str)
    except (ValueError, TypeError):
        return StepResult(status="failure", error=f"Некорректный pipeline_id: {pipeline_id_str}")

    from backend.models.pipeline import Pipeline, PipelineRunStatus

    pipeline = await db.scalar(
        select(Pipeline).where(Pipeline.id == pipeline_id, Pipeline.org_id == run.org_id)
    )
    if not pipeline:
        return StepResult(status="failure", error=f"Вложенный pipeline {pipeline_id_str} не найден")

    # Создать sub-run
    sub_run = PipelineRun(
        org_id=run.org_id,
        pipeline_id=pipeline_id,
        device_id=run.device_id,
        status=PipelineRunStatus.QUEUED,
        input_params=sub_input,
        steps_snapshot=pipeline.steps,
        context={"parent_run_id": str(run.id)},
        step_logs=[],
    )
    db.add(sub_run)
    await db.commit()

    # Polling: ожидаем завершения sub-run
    poll_interval = 1.0
    while True:
        await asyncio.sleep(poll_interval)
        await db.refresh(sub_run)
        if sub_run.status in (
            PipelineRunStatus.COMPLETED,
            PipelineRunStatus.FAILED,
            PipelineRunStatus.CANCELLED,
            PipelineRunStatus.TIMED_OUT,
        ):
            break

    if sub_run.status == PipelineRunStatus.COMPLETED:
        return StepResult(
            status="success",
            output={"sub_run_id": str(sub_run.id), "status": sub_run.status},
            context_updates={"sub_pipeline_result": sub_run.context},
        )
    else:
        return StepResult(
            status="failure",
            error=f"Вложенный pipeline завершился: {sub_run.status}",
            output={"sub_run_id": str(sub_run.id)},
        )


# ══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════════════


def _evaluate_condition(actual: Any, operator: str, expected: Any) -> bool:
    """Вычислить условие для шага condition."""
    if operator == "eq":
        return actual == expected
    elif operator == "neq":
        return actual != expected
    elif operator == "gt":
        return actual is not None and actual > expected
    elif operator == "lt":
        return actual is not None and actual < expected
    elif operator == "in":
        return actual in (expected or [])
    elif operator == "not_in":
        return actual not in (expected or [])
    elif operator == "exists":
        return actual is not None
    elif operator == "not_exists":
        return actual is None
    return False


# ══════════════════════════════════════════════════════════════════════════════
# Регистрация обработчиков
# ══════════════════════════════════════════════════════════════════════════════


StepHandlerRegistry.register("execute_script", handle_execute_script)
StepHandlerRegistry.register("condition", handle_condition)
StepHandlerRegistry.register("action", handle_action)
StepHandlerRegistry.register("delay", handle_delay)
StepHandlerRegistry.register("wait_for_event", handle_wait_for_event)
StepHandlerRegistry.register("parallel", handle_parallel)
StepHandlerRegistry.register("loop", handle_loop)
StepHandlerRegistry.register("n8n_workflow", handle_n8n_workflow)
StepHandlerRegistry.register("sub_pipeline", handle_sub_pipeline)
