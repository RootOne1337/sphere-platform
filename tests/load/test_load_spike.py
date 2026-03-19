# -*- coding: utf-8 -*-
"""
Spike-тест: резкий скачок 64 → 1024 → 64.

Запуск:
    pytest tests/load/test_load_spike.py -v -m load_spike
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.load.core.orchestrator import Orchestrator, TestConfig


@pytest.mark.load_spike
@pytest.mark.asyncio
async def test_spike_1024(config_dir: Path) -> None:
    """Spike-тест: 64 → 1024 → 64.

    Проверяет:
      - Thundering herd при резком скачке.
      - Восстановление после drop.
      - FA ≥ 90% во время спайка.
    """
    config_path = config_dir / "scenario_spike.yml"
    if not config_path.exists():
        pytest.skip(f"Конфиг не найден: {config_path}")

    config = TestConfig.from_yaml(config_path)
    orchestrator = Orchestrator(config)
    passed = await orchestrator.run()

    assert passed, "Spike-тест не пройден — см. отчёт в reports/spike/"


@pytest.mark.load_spike
@pytest.mark.asyncio
async def test_spike_reconnect_storm(
    base_url: str,
    ws_url: str,
    api_key: str,
) -> None:
    """Reconnect storm: 256 агентов, отключаем 30%, проверяем recovery."""
    from tests.load.core.agent_pool import AgentPool
    from tests.load.core.identity_factory import IdentityFactory
    from tests.load.core.metrics_collector import MetricsCollector
    from tests.load.core.virtual_agent import AgentBehavior
    from tests.load.scenarios.reconnect_storm import ReconnectStormScenario

    metrics = MetricsCollector()
    factory = IdentityFactory(org_id="load-test", seed=42)
    behavior = AgentBehavior(enable_vpn=False)

    pool = AgentPool(
        identity_factory=factory,
        behavior=behavior,
        metrics=metrics,
        base_url=base_url,
        ws_url=ws_url,
    )

    try:
        # Разворачиваем 256 агентов
        await pool.scale_to(256, ramp_duration_sec=45.0)
        await pool.wait_online(200, timeout=90.0)

        # Reconnect storm
        storm = ReconnectStormScenario(
            pool=pool,
            metrics=metrics,
            disconnect_pct=0.30,
            recovery_threshold=95.0,
            recovery_timeout=120.0,
        )
        result = await storm.run()

        assert result["recovered"], (
            f"Recovery не достигнут: FA={result['final_fa']}% "
            f"(порог={result['recovery_threshold']}%)"
        )

    finally:
        await pool.stop_all()
