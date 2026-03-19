# -*- coding: utf-8 -*-
"""
Сценарий S1: Массовая регистрация устройств.

Проверяет REST API /api/v1/devices/register при массовом
создании агентов. Измеряет latency, throughput, error rate.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.protocols.message_factory import MessageFactory
from tests.load.protocols.rest_client import RestClient

logger = logging.getLogger("loadtest.scenario.registration")


class DeviceRegistrationScenario:
    """Сценарий массовой регистрации устройств.

    Параметры:
        rest_client: REST-клиент.
        identity_factory: Фабрика идентичностей.
        metrics: Сборщик метрик.
        concurrency: Кол-во одновременных регистраций.
    """

    def __init__(
        self,
        rest_client: RestClient,
        identity_factory: IdentityFactory,
        metrics: MetricsCollector,
        concurrency: int = 50,
    ) -> None:
        self._rest = rest_client
        self._factory = identity_factory
        self._metrics = metrics
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self, count: int, start_index: int = 0) -> dict[str, Any]:
        """Зарегистрировать *count* устройств параллельно.

        Returns:
            Словарь с результатами: total, success, failed, latency_p50/p95/p99.
        """
        logger.info(
            "S1: Регистрация %d устройств (concurrency=%d)",
            count,
            self._semaphore._value,
        )

        t0 = time.monotonic()
        tasks = [
            self._register_one(start_index + i)
            for i in range(count)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for r in results if r is True)
        failed = count - success
        duration = time.monotonic() - t0

        self._metrics.inc("s1_total", count)
        self._metrics.inc("s1_success", success)
        self._metrics.inc("s1_failed", failed)

        summary = {
            "scenario": "S1_DeviceRegistration",
            "total": count,
            "success": success,
            "failed": failed,
            "duration_sec": round(duration, 2),
            "rps": round(count / max(duration, 0.01), 1),
        }
        logger.info("S1 результат: %s", summary)
        return summary

    async def _register_one(self, index: int) -> bool:
        """Зарегистрировать одно устройство."""
        identity = self._factory.create(index)
        payload = MessageFactory.device_register_payload(
            device_id=identity.device_id,
            serial=identity.serial,
            model=identity.model,
            android_version=identity.android_version,
            fingerprint=identity.fingerprint,
        )

        async with self._semaphore:
            status, body = await self._rest.register_device(payload)
            # 200 или 201 — успех; 409 — уже есть (тоже ок)
            return status in (200, 201, 409)
