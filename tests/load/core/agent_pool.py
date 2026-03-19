# -*- coding: utf-8 -*-
"""
Пул виртуальных агентов.

Управляет жизненным циклом N виртуальных агентов: запуск, масштабирование
вверх/вниз, остановка. Ramp-up реализован через линейную подачу агентов
с anti-stampede jitter.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.virtual_agent import AgentBehavior, AgentState, VirtualAgent

if TYPE_CHECKING:
    from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.pool")


class AgentPool:
    """Пул виртуальных агентов с динамическим масштабированием.

    Параметры:
        identity_factory: Фабрика идентичностей.
        behavior: Конфигурация поведения агентов.
        metrics: Сборщик метрик.
        base_url: Базовый HTTP URL сервера.
        ws_url: WebSocket URL сервера.
    """

    def __init__(
        self,
        identity_factory: IdentityFactory,
        behavior: AgentBehavior,
        metrics: MetricsCollector,
        base_url: str,
        ws_url: str,
    ) -> None:
        self._factory = identity_factory
        self._behavior = behavior
        self._metrics = metrics
        self._base_url = base_url
        self._ws_url = ws_url

        # Реестр: index -> (agent, task)
        self._agents: dict[int, VirtualAgent] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._next_index: int = 0

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Кол-во активных (не DEAD) агентов."""
        return sum(
            1
            for a in self._agents.values()
            if a.state not in (AgentState.DEAD, AgentState.CREATED)
        )

    @property
    def online_count(self) -> int:
        """Кол-во агентов в состоянии ONLINE или EXECUTING."""
        return sum(
            1
            for a in self._agents.values()
            if a.state in (AgentState.ONLINE, AgentState.EXECUTING)
        )

    @property
    def total_count(self) -> int:
        """Общее кол-во запущенных агентов."""
        return len(self._agents)

    async def scale_to(
        self,
        target: int,
        ramp_duration_sec: float = 60.0,
    ) -> None:
        """Масштабировать пул до *target* агентов.

        Если target > текущего — запускаем новых с рампой.
        Если target < текущего — останавливаем лишних.
        """
        current = self.total_count
        delta = target - current

        if delta > 0:
            await self._scale_up(delta, ramp_duration_sec)
        elif delta < 0:
            await self._scale_down(-delta, ramp_duration_sec)
        # delta == 0 — ничего не делаем

        self._metrics.set_gauge("pool_target_agents", float(target))
        self._metrics.set_gauge("pool_total_agents", float(self.total_count))

    async def wait_online(
        self, target: int, timeout: float = 120.0
    ) -> int:
        """Ожидать, пока ≥ *target* агентов будут ONLINE.

        Возвращает фактическое кол-во ONLINE по завершении.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            online = self.online_count
            self._metrics.set_gauge("pool_online_agents", float(online))
            if online >= target:
                return online
            await asyncio.sleep(1.0)
        return self.online_count

    async def stop_all(self, timeout: float = 30.0) -> None:
        """Graceful остановка всех агентов."""
        logger.info("Остановка %d агентов...", len(self._agents))
        # Отправляем stop всем
        coros = [a.stop() for a in self._agents.values()]
        await asyncio.gather(*coros, return_exceptions=True)

        # Ждём завершения asyncio tasks
        if self._tasks:
            _, pending = await asyncio.wait(
                self._tasks.values(), timeout=timeout
            )
            for t in pending:
                t.cancel()

        self._agents.clear()
        self._tasks.clear()
        logger.info("Все агенты остановлены")

    def get_fleet_availability(self) -> float:
        """Рассчитать Fleet Availability (%).

        FA = online / (total - dead) × 100
        """
        total = self.total_count
        dead = sum(
            1 for a in self._agents.values() if a.state == AgentState.DEAD
        )
        alive = total - dead
        if alive == 0:
            return 0.0
        return (self.online_count / alive) * 100.0

    def get_state_distribution(self) -> dict[str, int]:
        """Распределение агентов по состояниям."""
        dist: dict[str, int] = {}
        for a in self._agents.values():
            name = a.state.name
            dist[name] = dist.get(name, 0) + 1
        return dist

    # ---------------------------------------------------------------
    # Scale Up — запуск новых агентов с рампой
    # ---------------------------------------------------------------

    async def _scale_up(self, count: int, ramp_sec: float) -> None:
        """Запустить *count* новых агентов за *ramp_sec* секунд."""
        logger.info(
            "Scale UP: +%d агентов за %.0f сек (%.1f agents/sec)",
            count,
            ramp_sec,
            count / max(ramp_sec, 0.1),
        )

        delay_per_agent = ramp_sec / max(count, 1)

        for i in range(count):
            idx = self._next_index
            self._next_index += 1

            identity = self._factory.create(idx)

            # Определяем поведение: 5% — streamer, 8% — flaky, 2% — dead
            behavior = self._make_agent_behavior(idx)

            agent = VirtualAgent(
                identity=identity,
                behavior=behavior,
                metrics=self._metrics,
                base_url=self._base_url,
                ws_url=self._ws_url,
            )
            self._agents[idx] = agent

            # Запуск в фоне
            task = asyncio.create_task(
                agent.run(), name=f"agent-{identity.serial}"
            )
            self._tasks[idx] = task

            # Задержка для ramp-up (anti-stampede)
            if delay_per_agent > 0 and i < count - 1:
                await asyncio.sleep(delay_per_agent)

        self.metrics_update()

    # ---------------------------------------------------------------
    # Scale Down — остановка лишних агентов
    # ---------------------------------------------------------------

    async def _scale_down(self, count: int, ramp_sec: float) -> None:
        """Остановить *count* агентов за *ramp_sec* секунд."""
        logger.info("Scale DOWN: -%d агентов за %.0f сек", count, ramp_sec)

        delay_per_agent = ramp_sec / max(count, 1)

        # Останавливаем с конца (LIFO)
        indices = sorted(self._agents.keys(), reverse=True)
        stopped = 0

        for idx in indices:
            if stopped >= count:
                break
            agent = self._agents.get(idx)
            if agent is None:
                continue

            await agent.stop()

            task = self._tasks.pop(idx, None)
            if task is not None:
                task.cancel()

            del self._agents[idx]
            stopped += 1

            if delay_per_agent > 0 and stopped < count:
                await asyncio.sleep(delay_per_agent)

        self.metrics_update()

    # ---------------------------------------------------------------
    # Утилиты
    # ---------------------------------------------------------------

    def _make_agent_behavior(self, index: int) -> AgentBehavior:
        """Создать поведение агента с учётом распределения по ролям.

        30% idle (без задач), 55% worker, 5% streamer,
        8% flaky, 2% dead.
        """
        role_roll = index % 100

        if role_roll < 2:
            # Dead — сразу не подключится (max_retries=0)
            return AgentBehavior(
                max_reconnect_retries=0,
                task_success_rate=0,
                enable_vpn=False,
            )
        elif role_roll < 10:
            # Flaky — частые обрывы
            return AgentBehavior(
                random_disconnect_rate=0.005,  # 0.5% в минуту
                heartbeat_interval=self._behavior.heartbeat_interval,
                telemetry_interval=self._behavior.telemetry_interval,
                task_success_rate=self._behavior.task_success_rate,
                enable_vpn=self._behavior.enable_vpn,
            )
        elif role_roll < 15:
            # Streamer — worker + видео
            return AgentBehavior(
                heartbeat_interval=self._behavior.heartbeat_interval,
                telemetry_interval=self._behavior.telemetry_interval,
                task_success_rate=self._behavior.task_success_rate,
                enable_vpn=self._behavior.enable_vpn,
                enable_video=True,
                video_fps=self._behavior.video_fps,
            )
        elif role_roll < 45:
            # Idle — только heartbeat и telemetry
            return AgentBehavior(
                heartbeat_interval=self._behavior.heartbeat_interval,
                telemetry_interval=self._behavior.telemetry_interval,
                task_success_rate=0.0,  # Не выполняет задачи
                enable_vpn=self._behavior.enable_vpn,
            )
        else:
            # Worker — полный набор
            return AgentBehavior(
                heartbeat_interval=self._behavior.heartbeat_interval,
                telemetry_interval=self._behavior.telemetry_interval,
                task_success_rate=self._behavior.task_success_rate,
                task_failure_rate=self._behavior.task_failure_rate,
                task_duration_min=self._behavior.task_duration_min,
                task_duration_max=self._behavior.task_duration_max,
                enable_vpn=self._behavior.enable_vpn,
                random_disconnect_rate=self._behavior.random_disconnect_rate,
            )

    def metrics_update(self) -> None:
        """Обновить gauge-метрики пула."""
        self._metrics.set_gauge("pool_total_agents", float(self.total_count))
        self._metrics.set_gauge("pool_online_agents", float(self.online_count))
        self._metrics.set_gauge("pool_active_agents", float(self.active_count))
        self._metrics.set_gauge(
            "fleet_availability", self.get_fleet_availability()
        )
