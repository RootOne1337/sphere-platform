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
_RE_PARAMETER = re.compile(r"\{[^{}]+\}")


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Трекает latency и счётчик HTTP-запросов для всех эндпоинтов,
    кроме перечисленных в METRICS_SKIP_PATHS.

    Timing ends at response headers, not at the end of a streamed body.
    Exceptions are re-raised after being counted as 500; handlers retain control.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.scope["path"]

        if path in METRICS_SKIP_PATHS:
            return await call_next(request)

        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            # Routing has completed: use the declared template, never an
            # attacker-controlled URL, device identifier, or arbitrary method.
            route = request.scope.get("route")
            endpoint = _RE_PARAMETER.sub("{id}", getattr(route, "path", "__unmatched__"))
            method = request.method if request.method in _HTTP_METHODS else "OTHER"
            http_requests_total.labels(
                method=method, endpoint=endpoint, status_code=str(status_code),
            ).inc()
            http_request_duration_seconds.labels(
                method=method, endpoint=endpoint,
            ).observe(time.perf_counter() - start)


_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"})


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
