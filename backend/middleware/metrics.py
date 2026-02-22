# backend/middleware/metrics.py
# Prometheus HTTP metrics middleware для FastAPI.
# Подключается в backend/main.py через app.add_middleware(PrometheusMiddleware).
import re
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.core.constants import METRICS_SKIP_PATHS
from backend.metrics import http_request_duration_seconds, http_requests_total

# Скомпилированные regex — инициализируются один раз при импорте модуля.
_RE_UUID = re.compile(
    r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_RE_DIGITS = re.compile(r"/\d+")


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Трекает latency и счётчик HTTP-запросов для всех эндпоинтов,
    кроме перечисленных в METRICS_SKIP_PATHS.

    Важно: middleware должен стоять ПЕРЕД exception handlers, чтобы
    5xx-ответы тоже попадали в метрики (see: Step 4 порядок add_middleware).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        if path in METRICS_SKIP_PATHS:
            return await call_next(request)

        normalized = _normalize_path(path)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        http_requests_total.labels(
            method=request.method,
            endpoint=normalized,
            status_code=str(response.status_code),
        ).inc()

        http_request_duration_seconds.labels(
            method=request.method,
            endpoint=normalized,
        ).observe(duration)

        return response


def _normalize_path(path: str) -> str:
    """
    Нормализует сегменты пути, чтобы избежать label explosion.

    Примеры:
        /api/v1/devices/550e8400-e29b-41d4-a716-446655440000  →  /api/v1/devices/{id}
        /api/v1/tasks/123/logs                                →  /api/v1/tasks/{id}/logs
        /api/v1/devices/{id}/commands/456                     →  /api/v1/devices/{id}/commands/{id}
    """
    path = _RE_UUID.sub("/{id}", path)
    path = _RE_DIGITS.sub("/{id}", path)
    return path
