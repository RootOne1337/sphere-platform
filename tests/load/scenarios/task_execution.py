# -*- coding: utf-8 -*-
"""
Сценарий S3: Выполнение задач (Task Execution).

Проверяет полный цикл: сервер отправляет task_command → агент
выполняет → отправляет task_progress и command_result.

Работает поверх уже подключённого AgentPool.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tests.load.core.agent_pool import AgentPool
from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.scenario.task_execution")


class TaskExecutionScenario:
    """Сценарий массового выполнения задач.

    Параметры:
        pool: Пул виртуальных агентов (должны быть ONLINE).
        metrics: Сборщик метрик.
    """

    def __init__(
        self,
        pool: AgentPool,
        metrics: MetricsCollector,
    ) -> None:
        self._pool = pool
        self._metrics = metrics

    async def run(self, hold_sec: float = 120.0) -> dict[str, Any]:
        """Удерживать нагрузку *hold_sec* секунд.

        Задачи отправляются сервером (через task_command),
        виртуальные агенты обрабатывают их in-band через
        receiver_loop → _handle_task_command.

        Здесь мы просто мониторим метрики.
        """
        logger.info(
            "S3: Мониторинг выполнения задач %0.f сек "
            "(online=%d, active=%d)",
            hold_sec,
            self._pool.online_count,
            self._pool.active_count,
        )

        t0 = time.monotonic()
        snapshots: list[dict[str, Any]] = []

        while (time.monotonic() - t0) < hold_sec:
            await asyncio.sleep(10.0)
            snap = self._metrics.snapshot()
            snapshots.append(snap)

            counters = snap.get("counters", {})
            tasks_ok = counters.get("task_command_result_success", 0)
            tasks_fail = counters.get("task_command_result_error", 0)
            tasks_total = tasks_ok + tasks_fail

            fa = self._pool.get_fleet_availability()
            logger.info(
                "  S3 → FA=%.1f%%  tasks_total=%d  ok=%d  fail=%d",
                fa, tasks_total, tasks_ok, tasks_fail,
            )

        duration = time.monotonic() - t0
        final = self._metrics.snapshot()
        counters = final.get("counters", {})

        summary = {
            "scenario": "S3_TaskExecution",
            "duration_sec": round(duration, 2),
            "tasks_success": counters.get("task_command_result_success", 0),
            "tasks_error": counters.get("task_command_result_error", 0),
            "tasks_timeout": counters.get("task_command_result_timeout", 0),
            "fleet_availability": round(self._pool.get_fleet_availability(), 2),
            "online": self._pool.online_count,
        }
        logger.info("S3 результат: %s", summary)
        return summary
