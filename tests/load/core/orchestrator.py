# -*- coding: utf-8 -*-
"""
Оркестратор нагрузочного тестирования.

Читает конфигурацию, выполняет шаги (steps) последовательно:
  ramp_up → hold → [optional: spike] → ramp_down

На каждом шаге масштабирует AgentPool до целевого числа агентов,
собирает метрики, проверяет pass/fail критерии.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from tests.load.core.agent_pool import AgentPool
from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector, StepResult
from tests.load.core.report_generator import ReportGenerator
from tests.load.core.virtual_agent import AgentBehavior

logger = logging.getLogger("loadtest.orchestrator")


# ---------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------


@dataclass(frozen=True)
class StepConfig:
    """Конфигурация одного шага нагрузки."""

    name: str
    target_agents: int
    ramp_up_sec: float = 60.0
    hold_sec: float = 120.0
    ramp_down_sec: float = 30.0
    pass_criteria: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestConfig:
    """Полная конфигурация тестового прогона."""

    name: str = "load-test"
    base_url: str = "http://localhost:8000"
    ws_url: str = "ws://localhost:8000"
    api_key: str = ""
    seed: int = 42

    # Поведение агентов
    heartbeat_interval: float = 30.0
    telemetry_interval: float = 10.0
    task_success_rate: float = 0.80
    task_failure_rate: float = 0.15
    task_duration_min: float = 2.0
    task_duration_max: float = 30.0
    enable_vpn: bool = True
    enable_video: bool = False
    video_fps: int = 15
    random_disconnect_rate: float = 0.0001

    # Шаги
    steps: list[StepConfig] = field(default_factory=list)

    # Отчёт
    report_dir: str = "reports"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "TestConfig":
        """Загрузить конфиг из YAML-файла."""
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        steps_raw = raw.pop("steps", [])
        steps = [StepConfig(**s) for s in steps_raw]

        return cls(steps=steps, **raw)


# ---------------------------------------------------------------
# Pass/Fail Evaluator
# ---------------------------------------------------------------


class CriteriaEvaluator:
    """Проверяет pass/fail критерии по метрикам."""

    @staticmethod
    def evaluate(
        criteria: dict[str, Any], snapshot: dict[str, Any]
    ) -> list[str]:
        """Вернуть список нарушенных критериев (пустой → pass).

        Поддерживаемые операторы:
          fleet_availability_gte: 97.0
          p99_ws_connect_lte: 5000
          error_rate_lte: 0.05
        """
        violations: list[str] = []

        for key, threshold in criteria.items():
            if key.endswith("_gte"):
                metric_name = key[:-4]
                value = CriteriaEvaluator._resolve(metric_name, snapshot)
                if value is not None and value < threshold:
                    violations.append(
                        f"{metric_name}={value:.2f} < {threshold} (gte)"
                    )
            elif key.endswith("_lte"):
                metric_name = key[:-4]
                value = CriteriaEvaluator._resolve(metric_name, snapshot)
                if value is not None and value > threshold:
                    violations.append(
                        f"{metric_name}={value:.2f} > {threshold} (lte)"
                    )
            elif key.endswith("_lt"):
                metric_name = key[:-3]
                value = CriteriaEvaluator._resolve(metric_name, snapshot)
                if value is not None and value >= threshold:
                    violations.append(
                        f"{metric_name}={value:.2f} >= {threshold} (lt)"
                    )

        return violations

    @staticmethod
    def _resolve(name: str, snapshot: dict[str, Any]) -> float | None:
        """Найти значение метрики в snapshot."""
        # Прямой gauge
        gauges = snapshot.get("gauges", {})
        if name in gauges:
            return float(gauges[name])

        # Histogram p-значение: формат "metric_p99"
        parts = name.rsplit("_p", 1)
        if len(parts) == 2:
            hist_name = parts[0]
            percentile_key = f"p{parts[1]}"
            histograms = snapshot.get("histograms", {})
            hist_data = histograms.get(hist_name, {})
            if percentile_key in hist_data:
                return float(hist_data[percentile_key])

        # Counter
        counters = snapshot.get("counters", {})
        if name in counters:
            return float(counters[name])

        return None


# ---------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------


class Orchestrator:
    """Главный оркестратор нагрузочного тестирования.

    Выполняет шаги последовательно, собирает метрики,
    проверяет pass/fail, генерирует отчёт.
    """

    def __init__(self, config: TestConfig) -> None:
        self._config = config
        self._metrics = MetricsCollector()
        self._factory = IdentityFactory(org_id="load-test", seed=config.seed)
        self._behavior = AgentBehavior(
            heartbeat_interval=config.heartbeat_interval,
            telemetry_interval=config.telemetry_interval,
            task_success_rate=config.task_success_rate,
            task_failure_rate=config.task_failure_rate,
            task_duration_min=config.task_duration_min,
            task_duration_max=config.task_duration_max,
            enable_vpn=config.enable_vpn,
            enable_video=config.enable_video,
            video_fps=config.video_fps,
            random_disconnect_rate=config.random_disconnect_rate,
        )
        self._pool: AgentPool | None = None
        self._step_results: list[StepResult] = []
        self._report_dir = Path(config.report_dir)

    async def run(self) -> bool:
        """Выполнить все шаги и вернуть True, если тест пройден."""
        logger.info(
            "=" * 60
            + "\n  НАГРУЗОЧНЫЙ ТЕСТ: %s\n  Шагов: %d\n"
            + "=" * 60,
            self._config.name,
            len(self._config.steps),
        )

        self._pool = AgentPool(
            identity_factory=self._factory,
            behavior=self._behavior,
            metrics=self._metrics,
            base_url=self._config.base_url,
            ws_url=self._config.ws_url,
        )

        overall_passed = True
        overall_start = time.monotonic()

        try:
            for i, step in enumerate(self._config.steps, start=1):
                logger.info(
                    "\n--- Шаг %d/%d: %s (target=%d) ---",
                    i,
                    len(self._config.steps),
                    step.name,
                    step.target_agents,
                )

                step_passed = await self._run_step(step)
                if not step_passed:
                    overall_passed = False
                    logger.warning("Шаг '%s' — FAIL", step.name)
                else:
                    logger.info("Шаг '%s' — PASS", step.name)

        except Exception:
            logger.exception("Критическая ошибка в оркестраторе")
            overall_passed = False
        finally:
            # Остановка всех агентов
            if self._pool:
                await self._pool.stop_all(timeout=60.0)

        overall_duration = time.monotonic() - overall_start

        # Генерация отчёта
        self._generate_report(overall_passed, overall_duration)

        status = "PASS" if overall_passed else "FAIL"
        logger.info(
            "\n" + "=" * 60
            + "\n  РЕЗУЛЬТАТ: %s  (%.1f сек)\n"
            + "=" * 60,
            status,
            overall_duration,
        )
        return overall_passed

    # ---------------------------------------------------------------
    # Выполнение одного шага
    # ---------------------------------------------------------------

    async def _run_step(self, step: StepConfig) -> bool:
        """Выполнить один шаг: ramp_up → hold → metrics → ramp_down."""
        assert self._pool is not None
        step_start = time.monotonic()

        # 1. Ramp-up
        logger.info(
            "  [ramp-up] Масштабирование до %d за %.0f сек...",
            step.target_agents,
            step.ramp_up_sec,
        )
        await self._pool.scale_to(step.target_agents, step.ramp_up_sec)

        # 2. Ожидание выхода агентов в ONLINE
        stabilize_timeout = step.ramp_up_sec + 60.0
        # Ждём хотя бы 80% от target
        min_online = int(step.target_agents * 0.80)
        online = await self._pool.wait_online(min_online, stabilize_timeout)
        logger.info(
            "  [stabilize] ONLINE: %d / %d (target %d)",
            online,
            self._pool.total_count,
            step.target_agents,
        )

        # 3. Hold — основной замер
        logger.info("  [hold] Удержание %0.f сек...", step.hold_sec)
        hold_start = time.monotonic()

        # Собираем метрики каждые 5 секунд во время hold
        hold_snapshots: list[dict[str, Any]] = []
        while (time.monotonic() - hold_start) < step.hold_sec:
            await asyncio.sleep(5.0)
            snap = self._metrics.snapshot()
            hold_snapshots.append(snap)
            self._pool.metrics_update()

            # Логируем прогресс
            dist = self._pool.get_state_distribution()
            fa = self._pool.get_fleet_availability()
            logger.info(
                "    → FA=%.1f%%  dist=%s",
                fa,
                json.dumps(dist, ensure_ascii=False),
            )

        # 4. Финальный snapshot для оценки
        final_snap = self._metrics.snapshot()

        # 5. Оценка pass/fail
        violations = CriteriaEvaluator.evaluate(
            step.pass_criteria, final_snap
        )
        passed = len(violations) == 0

        if violations:
            for v in violations:
                logger.warning("    ✗ %s", v)

        # 6. Сохраняем StepResult
        step_duration = time.monotonic() - step_start
        result = StepResult(
            step_name=step.name,
            target_agents=step.target_agents,
            actual_online=self._pool.online_count,
            fleet_availability=self._pool.get_fleet_availability(),
            duration_sec=step_duration,
            passed=passed,
            violations=violations,
            snapshot=final_snap,
        )
        self._step_results.append(result)

        # 7. Не делаем ramp_down между шагами — следующий шаг
        #    масштабирует вверх/вниз автоматически
        return passed

    # ---------------------------------------------------------------
    # Отчёт
    # ---------------------------------------------------------------

    def _generate_report(
        self, overall_passed: bool, total_duration: float
    ) -> None:
        """Сгенерировать JSON и HTML отчёты."""
        self._report_dir.mkdir(parents=True, exist_ok=True)

        report_data = {
            "test_name": self._config.name,
            "overall_passed": overall_passed,
            "total_duration_sec": round(total_duration, 1),
            "steps": [],
        }

        for sr in self._step_results:
            report_data["steps"].append(
                {
                    "name": sr.step_name,
                    "target": sr.target_agents,
                    "actual_online": sr.actual_online,
                    "fleet_availability": round(sr.fleet_availability, 2),
                    "duration_sec": round(sr.duration_sec, 1),
                    "passed": sr.passed,
                    "violations": sr.violations,
                    "snapshot": sr.snapshot,
                }
            )

        # JSON
        json_path = self._report_dir / f"{self._config.name}-report.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        logger.info("JSON-отчёт: %s", json_path)

        # HTML
        try:
            html_path = self._report_dir / f"{self._config.name}-report.html"
            html = ReportGenerator.to_html(report_data)
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info("HTML-отчёт: %s", html_path)
        except Exception:
            logger.exception("Ошибка генерации HTML-отчёта")
