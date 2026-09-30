"""Actual ASGI requests prove bounded labels and exception accounting."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY

from backend.middleware.metrics import PrometheusMiddleware


@pytest.mark.asyncio
async def test_dynamic_routes_and_unknown_urls_have_bounded_labels():
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metric-canary/{name}")
    async def canary(name: str):
        return {"ok": True}

    route_labels = {"method": "GET", "endpoint": "/metric-canary/{name}", "status_code": "200"}
    other_labels = {"method": "OTHER", "endpoint": "__unmatched__", "status_code": "404"}
    before = REGISTRY.get_sample_value("sphere_http_requests_total", route_labels) or 0
    other_before = REGISTRY.get_sample_value("sphere_http_requests_total", other_labels) or 0
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        for index in range(20):
            assert (await client.get(f"/metric-canary/name-{index}")).status_code == 200
            assert (await client.request(f"CUSTOM{index}", f"/random-probe-{index}")).status_code == 404
    assert REGISTRY.get_sample_value("sphere_http_requests_total", route_labels) == before + 20
    assert REGISTRY.get_sample_value("sphere_http_requests_total", other_labels) == other_before + 20
    for family in REGISTRY.collect():
        if family.name == "sphere_http_requests":
            assert all("random-probe" not in sample.labels.get("endpoint", "") for sample in family.samples)
            assert all("name-" not in sample.labels.get("endpoint", "") for sample in family.samples)


@pytest.mark.asyncio
async def test_unhandled_exception_is_counted_as_500():
    app = FastAPI()
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metric-canary-error")
    async def canary_error():
        raise RuntimeError("isolated canary")

    labels = {"method": "GET", "endpoint": "/metric-canary-error", "status_code": "500"}
    before = REGISTRY.get_sample_value("sphere_http_requests_total", labels) or 0
    transport = ASGITransport(app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/metric-canary-error")).status_code == 500
    assert REGISTRY.get_sample_value("sphere_http_requests_total", labels) == before + 1
