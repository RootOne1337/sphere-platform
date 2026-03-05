# -*- coding: utf-8 -*-
"""
Сценарий S6-mixed: Комбинированная нагрузка (Mixed Workload).

Главный сценарий — объединяет ВСЕ виды нагрузки одновременно:
  - Регистрация устройств (S1)
  - WebSocket lifecycle (агенты из AgentPool)
  - Задачи (S3)
  - VPN (S4)
  - Видео (S5)
  - Reconnect storm (S6) — опционально

Распределение агентов:
  30% idle, 55% worker, 5% streamer, 8% flaky, 2% dead
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tests.load.core.agent_pool import AgentPool
from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.protocols.rest_client import RestClient
from tests.load.scenarios.device_registration import DeviceRegistrationScenario
from tests.load.scenarios.reconnect_storm import ReconnectStormScenario
from tests.load.scenarios.task_execution import TaskExecutionScenario
from tests.load.scenarios.video_streaming import VideoStreamingScenario
from tests.load.scenarios.vpn_enrollment import VpnEnrollmentScenario

logger = logging.getLogger("loadtest.scenario.mixed")


class MixedWorkloadScenario:
    """Комбинированный сценарий — все виды нагрузки параллельно.

    Параметры:
        pool: Пул виртуальных агентов.
        rest_client: REST-клиент.
        identity_factory: Фабрика идентичностей.
        metrics: Сборщик метрик.
    """

    def __init__(
        self,
        pool: AgentPool,
        rest_client: RestClient,
        identity_factory: IdentityFactory,
        metrics: MetricsCollector,
    ) -> None:
        self._pool = pool
        self._rest = rest_client
        self._factory = identity_factory
        self._metrics = metrics

    async def run(
        self,
        target_agents: int,
        hold_sec: float = 180.0,
        ramp_up_sec: float = 60.0,
        enable_reconnect_storm: bool = True,
    ) -> dict[str, Any]:
        """Выполнить комбинированный сценарий.

        Этапы:
          1. Регистрация устройств (REST).
          2. Масштабирование AgentPool (WS подключения).
          3. Hold: параллельный мониторинг задач + видео.
          4. (Опционально) reconnect storm.
          5. Сбор итогов.
        """
        results: dict[str, Any] = {
            "scenario": "MixedWorkload",
            "target_agents": target_agents,
        }
        t0 = time.monotonic()

        # ── Этап 1: Регистрация ──────────────────────────────────
        logger.info("MIXED: Этап 1 — Регистрация %d устройств", target_agents)
        reg_scenario = DeviceRegistrationScenario(
            rest_client=self._rest,
            identity_factory=self._factory,
            metrics=self._metrics,
            concurrency=min(100, target_agents),
        )
        results["registration"] = await reg_scenario.run(target_agents)

        # ── Этап 2: VPN enrollment (для всех) ────────────────────
        logger.info("MIXED: Этап 2 — VPN enrollment")
        vpn_scenario = VpnEnrollmentScenario(
            rest_client=self._rest,
            identity_factory=self._factory,
            metrics=self._metrics,
            concurrency=min(50, target_agents),
        )
        results["vpn"] = await vpn_scenario.run(target_agents)

        # ── Этап 3: Масштабирование пула ─────────────────────────
        logger.info(
            "MIXED: Этап 3 — Scale to %d за %.0f сек",
            target_agents,
            ramp_up_sec,
        )
        await self._pool.scale_to(target_agents, ramp_up_sec)
        online = await self._pool.wait_online(
            int(target_agents * 0.8), timeout=ramp_up_sec + 60.0
        )
        results["scale"] = {
            "target": target_agents,
            "online_after_ramp": online,
            "fa_after_ramp": round(self._pool.get_fleet_availability(), 2),
        }

        # ── Этап 4: Hold — параллельный мониторинг ───────────────
        logger.info("MIXED: Этап 4 — Hold %.0f сек", hold_sec)

        task_monitor = TaskExecutionScenario(self._pool, self._metrics)
        video_monitor = VideoStreamingScenario(self._pool, self._metrics)

        # Задачи и видео работают параллельно
        task_result, video_result = await asyncio.gather(
            task_monitor.run(hold_sec=hold_sec),
            video_monitor.run(hold_sec=hold_sec),
        )
        results["task_execution"] = task_result
        results["video_streaming"] = video_result

        # ── Этап 5: Reconnect Storm (опционально) ────────────────
        if enable_reconnect_storm and target_agents >= 64:
            logger.info("MIXED: Этап 5 — Reconnect Storm")
            storm = ReconnectStormScenario(
                pool=self._pool,
                metrics=self._metrics,
                disconnect_pct=0.30,
                recovery_threshold=95.0,
                recovery_timeout=120.0,
            )
            results["reconnect_storm"] = await storm.run()
        else:
            results["reconnect_storm"] = {"skipped": True}

        # ── Итоги ────────────────────────────────────────────────
        total_duration = time.monotonic() - t0
        results["total_duration_sec"] = round(total_duration, 2)
        results["final_fa"] = round(self._pool.get_fleet_availability(), 2)
        results["final_online"] = self._pool.online_count
        results["final_distribution"] = self._pool.get_state_distribution()

        logger.info(
            "MIXED ИТОГО: duration=%.0f сек  FA=%.1f%%  online=%d/%d",
            total_duration,
            results["final_fa"],
            results["final_online"],
            target_agents,
        )
        return results
