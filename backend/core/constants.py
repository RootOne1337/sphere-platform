# backend/core/constants.py
# LOW-6: централизованные константы, используемые в нескольких middleware/модулях.
# Импортируй отсюда — не дублируй в каждом файле.

# Пути, которые НЕ должны учитываться в Prometheus HTTP-метриках.
# Используется в PrometheusMiddleware (backend/middleware/metrics.py).
METRICS_SKIP_PATHS: frozenset[str] = frozenset({
    "/metrics",
    "/health",
    "/healthz",
    "/favicon.ico",
    "/api/v1/health",
    "/api/v1/health/ready",
})
