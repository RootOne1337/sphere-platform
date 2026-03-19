# -*- coding: utf-8 -*-
"""
Soak-тест: 512 агентов, 30 минут.

Запуск:
    pytest tests/load/test_load_soak.py -v -m load_soak
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.load.core.orchestrator import Orchestrator, TestConfig


@pytest.mark.load_soak
@pytest.mark.asyncio
async def test_soak_512(config_dir: Path) -> None:
    """Soak-тест: 512 агентов, 30 мин hold.

    Проверяет:
      - Утечки памяти (PG connections, Redis memory).
      - Стабильность FA ≥ 97% на длинной дистанции.
      - Дрифт метрик (latency не растёт со временем).
    """
    config_path = config_dir / "scenario_soak.yml"
    if not config_path.exists():
        pytest.skip(f"Конфиг не найден: {config_path}")

    config = TestConfig.from_yaml(config_path)
    orchestrator = Orchestrator(config)
    passed = await orchestrator.run()

    assert passed, "Soak-тест не пройден — см. отчёт в reports/soak/"
