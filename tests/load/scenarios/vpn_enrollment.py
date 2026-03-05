# -*- coding: utf-8 -*-
"""
Сценарий S4: VPN Enrollment.

Проверяет массовое назначение VPN-профилей через REST API
/api/v1/vpn/assign и периодическую проверку статуса /api/v1/vpn/status.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector
from tests.load.protocols.rest_client import RestClient

logger = logging.getLogger("loadtest.scenario.vpn")


class VpnEnrollmentScenario:
    """Сценарий массового VPN enrollment.

    Параметры:
        rest_client: REST-клиент.
        identity_factory: Фабрика идентичностей.
        metrics: Сборщик метрик.
        concurrency: Кол-во одновременных запросов.
    """

    def __init__(
        self,
        rest_client: RestClient,
        identity_factory: IdentityFactory,
        metrics: MetricsCollector,
        concurrency: int = 30,
    ) -> None:
        self._rest = rest_client
        self._factory = identity_factory
        self._metrics = metrics
        self._semaphore = asyncio.Semaphore(concurrency)

    async def run(self, count: int, start_index: int = 0) -> dict[str, Any]:
        """Назначить VPN-профили *count* устройствам.

        Returns:
            Словарь результатов: total, success, failed, latency.
        """
        logger.info("S4: VPN Enrollment для %d устройств", count)
        t0 = time.monotonic()

        tasks = [
            self._enroll_one(start_index + i)
            for i in range(count)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success = sum(1 for r in results if r is True)
        failed = count - success
        duration = time.monotonic() - t0

        self._metrics.inc("s4_total", count)
        self._metrics.inc("s4_success", success)
        self._metrics.inc("s4_failed", failed)

        summary = {
            "scenario": "S4_VpnEnrollment",
            "total": count,
            "success": success,
            "failed": failed,
            "duration_sec": round(duration, 2),
            "rps": round(count / max(duration, 0.01), 1),
        }
        logger.info("S4 результат: %s", summary)
        return summary

    async def _enroll_one(self, index: int) -> bool:
        """Назначить VPN одному устройству."""
        identity = self._factory.create(index)

        async with self._semaphore:
            status, body = await self._rest.assign_vpn(identity.device_id)
            if status in (200, 201):
                return True

            # 409 — уже назначен (ок для повторных запусков)
            if status == 409:
                return True

            return False
