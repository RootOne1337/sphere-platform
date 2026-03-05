# -*- coding: utf-8 -*-
"""
REST-клиент для нагрузочного тестирования.

Обёртка над aiohttp.ClientSession с метриками, ретраями,
и rate-limiting для REST API Sphere Platform.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.rest")

# Кол-во одновременных HTTP-запросов (семафор)
_DEFAULT_CONCURRENCY = 200
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0


class RestClient:
    """Асинхронный REST-клиент с метриками и ретраями.

    Параметры:
        base_url: Базовый URL (например, http://localhost:8000).
        metrics: Сборщик метрик.
        api_key: API-ключ для заголовка X-API-Key.
        concurrency: Макс. кол-во одновременных запросов.
        timeout: Таймаут одного запроса (сек).
    """

    def __init__(
        self,
        base_url: str,
        metrics: MetricsCollector,
        api_key: str = "",
        concurrency: int = _DEFAULT_CONCURRENCY,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._metrics = metrics
        self._api_key = api_key
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Ленивая инициализация aiohttp.ClientSession."""
        if self._session is None or self._session.closed:
            headers: dict[str, str] = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self._api_key:
                headers["X-API-Key"] = self._api_key

            connector = aiohttp.TCPConnector(
                limit=_DEFAULT_CONCURRENCY,
                ttl_dns_cache=300,
                enable_cleanup_closed=True,
            )
            self._session = aiohttp.ClientSession(
                base_url=self._base_url,
                headers=headers,
                connector=connector,
                timeout=self._timeout,
            )
        return self._session

    async def close(self) -> None:
        """Закрыть HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    # ---------------------------------------------------------------
    # Запросы
    # ---------------------------------------------------------------

    async def post(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
        *,
        retries: int = _MAX_RETRIES,
        metric_name: str = "",
    ) -> tuple[int, dict[str, Any] | None]:
        """POST-запрос с метриками и ретраями.

        Returns:
            (status_code, response_json | None)
        """
        return await self._request(
            "POST", path, json_data=json_data, retries=retries,
            metric_name=metric_name,
        )

    async def get(
        self,
        path: str,
        *,
        retries: int = _MAX_RETRIES,
        metric_name: str = "",
    ) -> tuple[int, dict[str, Any] | None]:
        """GET-запрос с метриками."""
        return await self._request(
            "GET", path, retries=retries, metric_name=metric_name,
        )

    async def put(
        self,
        path: str,
        json_data: dict[str, Any] | None = None,
        *,
        retries: int = _MAX_RETRIES,
        metric_name: str = "",
    ) -> tuple[int, dict[str, Any] | None]:
        """PUT-запрос с метриками."""
        return await self._request(
            "PUT", path, json_data=json_data, retries=retries,
            metric_name=metric_name,
        )

    # ---------------------------------------------------------------
    # Внутренняя логика
    # ---------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        retries: int = _MAX_RETRIES,
        metric_name: str = "",
    ) -> tuple[int, dict[str, Any] | None]:
        """Выполнить HTTP-запрос с ретраями, семафором и метриками."""
        label = metric_name or f"{method}_{path.strip('/').replace('/', '_')}"

        for attempt in range(1, retries + 1):
            async with self._semaphore:
                t0 = time.monotonic()
                try:
                    session = await self._get_session()
                    async with session.request(
                        method, path, json=json_data
                    ) as resp:
                        latency_ms = (time.monotonic() - t0) * 1000
                        self._metrics.record(f"rest_{label}_latency", latency_ms)
                        self._metrics.inc(f"rest_{label}_total")

                        body = None
                        if resp.content_type == "application/json":
                            body = await resp.json()

                        if resp.status >= 500 and attempt < retries:
                            self._metrics.inc(f"rest_{label}_retry")
                            await asyncio.sleep(_RETRY_BACKOFF * attempt)
                            continue

                        if resp.status >= 400:
                            self._metrics.inc(f"rest_{label}_error")

                        return resp.status, body

                except asyncio.TimeoutError:
                    self._metrics.inc(f"rest_{label}_timeout")
                    if attempt < retries:
                        await asyncio.sleep(_RETRY_BACKOFF * attempt)
                        continue
                    return 0, None

                except aiohttp.ClientError as exc:
                    self._metrics.inc(f"rest_{label}_error")
                    logger.debug(
                        "REST %s %s attempt %d/%d: %s",
                        method, path, attempt, retries, exc,
                    )
                    if attempt < retries:
                        await asyncio.sleep(_RETRY_BACKOFF * attempt)
                        continue
                    return 0, None

        return 0, None

    # ---------------------------------------------------------------
    # Sphere-специфичные методы
    # ---------------------------------------------------------------

    async def register_device(
        self, payload: dict[str, Any]
    ) -> tuple[int, dict[str, Any] | None]:
        """POST /api/v1/devices/register."""
        return await self.post(
            "/api/v1/devices/register",
            json_data=payload,
            metric_name="device_register",
        )

    async def assign_vpn(
        self, device_id: str
    ) -> tuple[int, dict[str, Any] | None]:
        """POST /api/v1/vpn/assign."""
        return await self.post(
            "/api/v1/vpn/assign",
            json_data={"device_id": device_id},
            metric_name="vpn_assign",
        )

    async def check_vpn_status(
        self, device_id: str
    ) -> tuple[int, dict[str, Any] | None]:
        """GET /api/v1/vpn/status/{device_id}."""
        return await self.get(
            f"/api/v1/vpn/status/{device_id}",
            metric_name="vpn_status",
        )

    async def get_device_info(
        self, device_id: str
    ) -> tuple[int, dict[str, Any] | None]:
        """GET /api/v1/devices/{device_id}."""
        return await self.get(
            f"/api/v1/devices/{device_id}",
            metric_name="device_info",
        )
