# -*- coding: utf-8 -*-
"""
Сборщик метрик нагрузочного теста.

Потокобезопасный (asyncio-safe) агрегатор метрик c HdrHistogram для
точных перцентилей и атомарными счётчиками.

Экспортирует результат в dict / JSON для отчёта и опционально
пушит в Prometheus Push Gateway.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("loadtest.metrics")

# ---------------------------------------------------------------------------
# HdrHistogram — опциональная зависимость; при отсутствии fallback на list
# ---------------------------------------------------------------------------
try:
    from hdrh.histogram import HdrHistogram as _Hdr

    _HAS_HDR = True
except ImportError:  # pragma: no cover
    _HAS_HDR = False


class _FallbackHistogram:
    """Упрощённая замена HdrHistogram для среды без C-расширения."""

    def __init__(self) -> None:
        self._values: list[float] = []

    def record_value(self, v: int) -> None:
        self._values.append(v)

    @property
    def total_count(self) -> int:
        return len(self._values)

    @property
    def min_value(self) -> float:
        return min(self._values) if self._values else 0

    @property
    def max_value(self) -> float:
        return max(self._values) if self._values else 0

    def get_mean_value(self) -> float:
        return sum(self._values) / len(self._values) if self._values else 0

    def get_value_at_percentile(self, p: float) -> float:
        if not self._values:
            return 0
        s = sorted(self._values)
        idx = int(len(s) * p / 100)
        idx = min(idx, len(s) - 1)
        return s[idx]


# ---------------------------------------------------------------------------
# Доменные типы
# ---------------------------------------------------------------------------


class MetricKind(str, Enum):
    """Тип метрики."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class StepResult:
    """Результат одной ступени нагрузочного теста."""

    step_name: str
    target_agents: int
    actual_online: int = 0
    fleet_availability: float = 0.0
    duration_sec: float = 0.0
    passed: bool = True
    violations: list[str] = field(default_factory=list)
    snapshot: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Центральный сборщик метрик нагрузочного теста.

    Потокобезопасен в рамках одного event-loop (asyncio).
    Для каждой ступени теста создаётся snapshot, который затем
    попадает в итоговый отчёт.
    """

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, Any] = {}
        self._step_results: list[StepResult] = []
        self._start_ts: float = time.monotonic()
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------
    # Счётчики
    # ---------------------------------------------------------------

    def inc(self, name: str, delta: int = 1) -> None:
        """Инкрементировать счётчик *name* на *delta*."""
        self._counters[name] = self._counters.get(name, 0) + delta

    def counter(self, name: str) -> int:
        """Получить текущее значение счётчика."""
        return self._counters.get(name, 0)

    # ---------------------------------------------------------------
    # Gauge (мгновенное значение)
    # ---------------------------------------------------------------

    def set_gauge(self, name: str, value: float) -> None:
        """Установить мгновенное значение."""
        self._gauges[name] = value

    def gauge(self, name: str) -> float:
        """Получить текущее значение gauge."""
        return self._gauges.get(name, 0.0)

    # ---------------------------------------------------------------
    # Гистограмма
    # ---------------------------------------------------------------

    def record(self, name: str, value_ms: float) -> None:
        """Записать значение в гистограмму *name* (в миллисекундах)."""
        if name not in self._histograms:
            if _HAS_HDR:
                self._histograms[name] = _Hdr(1, 120_000, 3)
            else:
                self._histograms[name] = _FallbackHistogram()
        v = max(1, int(value_ms))
        try:
            self._histograms[name].record_value(v)
        except Exception:
            pass  # Выход за диапазон — игнорируем

    def histogram_summary(self, name: str) -> dict[str, float]:
        """Получить сводку гистограммы (count, min, max, p50..p999)."""
        h = self._histograms.get(name)
        if h is None:
            return {}
        return {
            "count": h.total_count,
            "min": h.min_value,
            "max": h.max_value,
            "mean": round(h.get_mean_value(), 2),
            "p50": h.get_value_at_percentile(50.0),
            "p75": h.get_value_at_percentile(75.0),
            "p90": h.get_value_at_percentile(90.0),
            "p95": h.get_value_at_percentile(95.0),
            "p99": h.get_value_at_percentile(99.0),
            "p999": h.get_value_at_percentile(99.9),
        }

    # ---------------------------------------------------------------
    # Ступени
    # ---------------------------------------------------------------

    def start_step(self, step_name: str, target_agents: int) -> StepResult:
        """Начать замер ступени."""
        sr = StepResult(step_name=step_name, target_agents=target_agents)
        self._step_results.append(sr)
        return sr

    def finish_step(
        self,
        sr: StepResult,
        *,
        actual_peak: int,
        duration: float,
        passed: bool = True,
    ) -> None:
        """Завершить ступень и зафиксировать метрики."""
        sr.actual_agents_peak = actual_peak
        sr.duration_seconds = round(duration, 2)
        sr.passed = passed
        sr.metrics = self.snapshot()

    @property
    def steps(self) -> list[StepResult]:
        return list(self._step_results)

    # ---------------------------------------------------------------
    # Снимок (snapshot)
    # ---------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Полный снимок всех метрик на текущий момент."""
        result: dict[str, Any] = {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": {},
            "elapsed_sec": round(time.monotonic() - self._start_ts, 2),
        }
        for name in self._histograms:
            result["histograms"][name] = self.histogram_summary(name)
        return result

    def reset_histograms(self) -> None:
        """Сброс гистограмм (между ступенями)."""
        self._histograms.clear()

    # ---------------------------------------------------------------
    # Экспорт
    # ---------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Полный отчёт в виде dict (json-serializable)."""
        return {
            "steps": [
                {
                    "name": s.step_name,
                    "target_agents": s.target_agents,
                    "actual_online": s.actual_online,
                    "fleet_availability": s.fleet_availability,
                    "duration_sec": s.duration_sec,
                    "passed": s.passed,
                    "violations": s.violations,
                    "snapshot": s.snapshot,
                }
                for s in self._step_results
            ],
            "final_snapshot": self.snapshot(),
        }

    def save_json(self, path: Path) -> None:
        """Сохранить отчёт в JSON-файл."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        logger.info("Отчёт сохранён: %s", path)
