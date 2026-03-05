# -*- coding: utf-8 -*-
"""
Полный тест масштабируемости: 32 → 10000 агентов.

Запуск:
    pytest tests/load/test_load_scalability.py -v -m load_scalability
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.load.core.orchestrator import Orchestrator, TestConfig


@pytest.mark.load_scalability
@pytest.mark.asyncio
async def test_scalability_full(config_dir: Path) -> None:
    """Полный scalability-тест: 32 → 10000 агентов."""
    config_path = config_dir / "scenario_scalability.yml"
    if not config_path.exists():
        pytest.skip(f"Конфиг не найден: {config_path}")

    config = TestConfig.from_yaml(config_path)
    orchestrator = Orchestrator(config)
    passed = await orchestrator.run()

    assert passed, (
        "Scalability-тест не пройден — "
        "см. отчёт в reports/scalability/"
    )


@pytest.mark.load_scalability
@pytest.mark.asyncio
async def test_scalability_to_512(config_dir: Path) -> None:
    """Частичный scalability: до 512 (минимальная победа)."""
    config_path = config_dir / "scenario_scalability.yml"
    if not config_path.exists():
        pytest.skip(f"Конфиг не найден: {config_path}")

    config = TestConfig.from_yaml(config_path)

    # Обрезаем до 512
    config.steps = [s for s in config.steps if s.target_agents <= 512]
    config.name = "scalability-512"
    config.report_dir = "reports/scalability-512"

    orchestrator = Orchestrator(config)
    passed = await orchestrator.run()

    assert passed, "Scalability до 512 не пройден"


@pytest.mark.load_scalability
@pytest.mark.asyncio
async def test_scalability_to_1024(config_dir: Path) -> None:
    """Частичный scalability: до 1024 (целевая победа)."""
    config_path = config_dir / "scenario_scalability.yml"
    if not config_path.exists():
        pytest.skip(f"Конфиг не найден: {config_path}")

    config = TestConfig.from_yaml(config_path)

    # Обрезаем до 1024
    config.steps = [s for s in config.steps if s.target_agents <= 1024]
    config.name = "scalability-1024"
    config.report_dir = "reports/scalability-1024"

    orchestrator = Orchestrator(config)
    passed = await orchestrator.run()

    assert passed, "Scalability до 1024 не пройден"
