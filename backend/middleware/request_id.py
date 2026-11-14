# backend/middleware/request_id.py
# TZ-11 SPLIT-4: X-Request-ID middleware.
# Добавляет уникальный request_id к каждому запросу и ответу.
# Привязывает request_id к structlog ContextVar — все логи в рамках запроса
# автоматически включают этот ID без явной передачи.
import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}"


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware для сквозной прослеживаемости запросов.

    Поведение:
    - Принимает `X-Request-ID` из входящего запроса (если есть).
    - При отсутствии корректного заголовка генерирует UUID.
    - Привязывает request_id, method, path к structlog ContextVar.
    - Добавляет `X-Request-ID` к каждому ответу.

    Пример лога (JSON):
        {"event": "user.login", "request_id": "a1b2c3d4", "method": "POST", "path": "/api/v1/auth/login"}
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Принять входящий ID или сгенерировать новый
        supplied_id = request.headers.get("X-Request-ID")
        request_id = supplied_id if supplied_id and re.fullmatch(REQUEST_ID_PATTERN, supplied_id) else uuid.uuid4().hex
        request.state.request_id = request_id

        # Очищаем контекст предыдущего запроса (важно для async workers)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.scope["path"],
        )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        return response
