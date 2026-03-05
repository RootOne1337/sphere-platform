# -*- coding: utf-8 -*-
"""
Сценарий S6: Reconnect Storm.

Имитирует массовое переподключение агентов (thundering herd).
Одновременно отключает X% агентов и замеряет время восстановления
Fleet Availability до ≥ 95%.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

from tests.load.core.agent_pool import AgentPool
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.virtual_agent import AgentState

logger = logging.getLogger("loadtest.scenario.reconnect")


class ReconnectStormScenario:
    """Сценарий массового переподключения (thundering herd).

    Параметры:
        pool: Пул виртуальных агентов.
        metrics: Сборщик метрик.
        disconnect_pct: Доля агентов для отключения (0.0–1.0).
        recovery_threshold: FA порог восстановления (%).
        recovery_timeout: Макс. время ожидания восстановления (сек).
    """

    def __init__(
        self,
        pool: AgentPool,
        metrics: MetricsCollector,
        disconnect_pct: float = 0.30,
        recovery_threshold: float = 95.0,
        recovery_timeout: float = 120.0,
    ) -> None:
        self._pool = pool
        self._metrics = metrics
        self._disconnect_pct = disconnect_pct
        self._recovery_threshold = recovery_threshold
        self._recovery_timeout = recovery_timeout

    async def run(self) -> dict[str, Any]:
        """Выполнить reconnect storm.

        1. Зафиксировать начальный FA.
        2. Отключить disconnect_pct агентов (закрыть WS).
        3. Измерить время восстановления FA до recovery_threshold.
        """
        # 1. Начальное состояние
        initial_fa = self._pool.get_fleet_availability()
        initial_online = self._pool.online_count
        total = self._pool.total_count

        to_disconnect = int(total * self._disconnect_pct)
        logger.info(
            "S6: Reconnect Storm — отключаем %d/%d агентов "
            "(FA до: %.1f%%, порог: %.1f%%)",
            to_disconnect,
            total,
            initial_fa,
            self._recovery_threshold,
        )

        # 2. Отключение — вызываем stop для случайных агентов
        #    Они автоматически reconnect через backoff
        agents = list(self._pool._agents.values())
        targets = random.sample(
            [a for a in agents if a.state in (AgentState.ONLINE, AgentState.EXECUTING)],
            min(to_disconnect, len(agents)),
        )

        t0 = time.monotonic()

        # Принудительно закрываем их WS (не stop, чтобы они переподключились)
        disconnect_coros = []
        for agent in targets:
            # Сбрасываем _ws_connected — агент в receiver_loop получит ошибку
            # и инициирует reconnect
            if hasattr(agent, "_ws") and agent._ws is not None:
                disconnect_coros.append(agent._ws.close(1001, "storm"))
        await asyncio.gather(*disconnect_coros, return_exceptions=True)

        disconnect_time = time.monotonic() - t0
        post_fa = self._pool.get_fleet_availability()
        logger.info(
            "  S6 → Отключено за %.1f сек, FA после: %.1f%%",
            disconnect_time,
            post_fa,
        )

        self._metrics.inc("s6_disconnected", to_disconnect)
        self._metrics.set_gauge("s6_post_disconnect_fa", post_fa)

        # 3. Ожидание восстановления
        recovery_start = time.monotonic()
        recovered = False

        while (time.monotonic() - recovery_start) < self._recovery_timeout:
            await asyncio.sleep(2.0)
            current_fa = self._pool.get_fleet_availability()
            current_online = self._pool.online_count
            logger.info(
                "  S6 recovery → FA=%.1f%% online=%d/%d",
                current_fa,
                current_online,
                total,
            )
            if current_fa >= self._recovery_threshold:
                recovered = True
                break

        recovery_sec = time.monotonic() - recovery_start
        final_fa = self._pool.get_fleet_availability()

        self._metrics.record("s6_recovery_time", recovery_sec * 1000)
        self._metrics.set_gauge("s6_final_fa", final_fa)

        summary = {
            "scenario": "S6_ReconnectStorm",
            "total_agents": total,
            "disconnected": to_disconnect,
            "disconnect_pct": round(self._disconnect_pct * 100, 1),
            "initial_fa": round(initial_fa, 2),
            "post_disconnect_fa": round(post_fa, 2),
            "final_fa": round(final_fa, 2),
            "recovery_sec": round(recovery_sec, 2),
            "recovered": recovered,
            "recovery_threshold": self._recovery_threshold,
        }
        logger.info("S6 результат: %s", summary)
        return summary
