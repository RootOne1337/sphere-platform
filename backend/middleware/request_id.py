# backend/middleware/request_id.py
# TZ-11 SPLIT-4: X-Request-ID middleware.
# Добавляет уникальный request_id к каждому запросу и ответу.
# Привязывает request_id к structlog ContextVar — все логи в рамках запроса
# автоматически включают этот ID без явной передачи.
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware для сквозной прослеживаемости запросов.

    Поведение:
    - Принимает `X-Request-ID` из входящего запроса (если есть).
    - Если заголовка нет — генерирует короткий UUID (8 символов).
    - Привязывает request_id, method, path к structlog ContextVar.
    - Добавляет `X-Request-ID` к каждому ответу.

    Пример лога (JSON):
        {"event": "user.login", "request_id": "a1b2c3d4", "method": "POST", "path": "/api/v1/auth/login"}
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Принять входящий ID или сгенерировать новый
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]

        # Очищаем контекст предыдущего запроса (важно для async workers)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response
