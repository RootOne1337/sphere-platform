# -*- coding: utf-8 -*-
"""
Quick smoke-тест: 32 → 64 → 128 агентов.

Запуск:
    pytest tests/load/test_load_quick.py -v -m load_quick
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.load.core.orchestrator import Orchestrator, TestConfig


@pytest.mark.load_quick
@pytest.mark.asyncio
async def test_quick_smoke(config_dir: Path) -> None:
    """Smoke-тест: 32 → 64 → 128 агентов, FA ≥ 97%."""
    config_path = config_dir / "scenario_quick.yml"
    if not config_path.exists():
        pytest.skip(f"Конфиг не найден: {config_path}")

    config = TestConfig.from_yaml(config_path)
    orchestrator = Orchestrator(config)
    passed = await orchestrator.run()

    assert passed, "Quick smoke-тест не пройден — см. отчёт в reports/quick/"


@pytest.mark.load_quick
@pytest.mark.asyncio
async def test_quick_mixed(
    base_url: str,
    ws_url: str,
    api_key: str,
) -> None:
    """Quick mixed-сценарий: 64 агента, 60 сек hold."""
    from tests.load.core.agent_pool import AgentPool
    from tests.load.core.identity_factory import IdentityFactory
    from tests.load.core.metrics_collector import MetricsCollector
    from tests.load.core.virtual_agent import AgentBehavior
    from tests.load.protocols.rest_client import RestClient
    from tests.load.scenarios.mixed_workload import MixedWorkloadScenario

    metrics = MetricsCollector()
    factory = IdentityFactory(org_id="load-test", seed=42)
    behavior = AgentBehavior(enable_vpn=True)

    pool = AgentPool(
        identity_factory=factory,
        behavior=behavior,
        metrics=metrics,
        base_url=base_url,
        ws_url=ws_url,
    )
    rest = RestClient(base_url=base_url, metrics=metrics, api_key=api_key)

    try:
        scenario = MixedWorkloadScenario(
            pool=pool,
            rest_client=rest,
            identity_factory=factory,
            metrics=metrics,
        )
        results = await scenario.run(
            target_agents=64,
            hold_sec=60.0,
            ramp_up_sec=15.0,
            enable_reconnect_storm=False,
        )

        fa = results.get("final_fa", 0)
        assert fa >= 90.0, f"FA={fa}% < 90% — тест не пройден"

    finally:
        await pool.stop_all()
        await rest.close()
