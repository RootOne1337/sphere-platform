# -*- coding: utf-8 -*-
"""
Pytest fixtures для нагрузочных тестов Sphere Platform.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import AsyncGenerator, Generator

import pytest

from tests.load.core.agent_pool import AgentPool
from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.core.virtual_agent import AgentBehavior
from tests.load.protocols.rest_client import RestClient

# ---------------------------------------------------------------
# Конфигурация из env-переменных
# ---------------------------------------------------------------

BASE_URL = os.getenv("LOAD_TEST_BASE_URL", "http://localhost:8000")
WS_URL = os.getenv("LOAD_TEST_WS_URL", "ws://localhost:8000")
API_KEY = os.getenv("LOAD_TEST_API_KEY", "")


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Единый event loop для всей сессии."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def base_url() -> str:
    return BASE_URL


@pytest.fixture(scope="session")
def ws_url() -> str:
    return WS_URL


@pytest.fixture(scope="session")
def api_key() -> str:
    return API_KEY


@pytest.fixture
def metrics() -> MetricsCollector:
    """Свежий MetricsCollector для каждого теста."""
    return MetricsCollector()


@pytest.fixture
def identity_factory() -> IdentityFactory:
    """Фабрика идентичностей с фиксированным seed."""
    return IdentityFactory(org_id="load-test", seed=42)


@pytest.fixture
def behavior() -> AgentBehavior:
    """Стандартное поведение агента."""
    return AgentBehavior()


@pytest.fixture
async def rest_client(
    base_url: str, metrics: MetricsCollector, api_key: str
) -> AsyncGenerator[RestClient, None]:
    """REST-клиент с автоматическим закрытием."""
    client = RestClient(
        base_url=base_url,
        metrics=metrics,
        api_key=api_key,
    )
    yield client
    await client.close()


@pytest.fixture
async def agent_pool(
    identity_factory: IdentityFactory,
    behavior: AgentBehavior,
    metrics: MetricsCollector,
    base_url: str,
    ws_url: str,
) -> AsyncGenerator[AgentPool, None]:
    """AgentPool с автоматической остановкой."""
    pool = AgentPool(
        identity_factory=identity_factory,
        behavior=behavior,
        metrics=metrics,
        base_url=base_url,
        ws_url=ws_url,
    )
    yield pool
    await pool.stop_all(timeout=10.0)


@pytest.fixture
def config_dir() -> Path:
    """Путь к директории конфигов."""
    return Path(__file__).parent / "config"


@pytest.fixture
def fixtures_dir() -> Path:
    """Путь к директории fixtures."""
    return Path(__file__).parent / "fixtures"


def pytest_configure(config: pytest.Config) -> None:
    """Регистрация пользовательских маркеров."""
    config.addinivalue_line(
        "markers",
        "load_quick: Быстрый smoke-тест нагрузки (< 5 мин)",
    )
    config.addinivalue_line(
        "markers",
        "load_scalability: Полный тест масштабируемости (32 → 10000)",
    )
    config.addinivalue_line(
        "markers",
        "load_soak: Длительный soak-тест (30+ мин)",
    )
    config.addinivalue_line(
        "markers",
        "load_spike: Spike-тест (резкий скачок)",
    )
