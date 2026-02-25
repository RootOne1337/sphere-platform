# backend/middleware/audit.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-5. Автоматический audit log через ASGI middleware.
# Записывает все mutating HTTP запросы после отправки ответа клиенту (BackgroundTask).
from __future__ import annotations

import inspect
import re
import time

import structlog
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response

from backend.database.engine import AsyncSessionLocal
from backend.models.audit_log import AuditLog

logger = structlog.get_logger()

# Только эти методы триггерят audit entry
AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Пути которые пропускаем (высокочастотные / не несут бизнес-смысла)
SKIP_PATHS = frozenset({
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/auth/refresh",
    "/api/v1/auth/me",
    "/metrics",
    "/api/docs",
    "/api/redoc",
})

# Извлечь resource_type из URL (последний значащий сегмент пути)
_RESOURCE_RE = re.compile(r"/api/v\d+/([a-z_-]+)")

# UUIDv4 паттерн для определения ID-сегментов
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)


def _path_to_action(method: str, path: str) -> str:
    """Нормализовать HTTP метод + path в action-строку типа 'post.devices'."""
    resource = _extract_resource_type(path)
    return f"{method.lower()}.{resource}"


def _extract_resource_type(path: str) -> str:
    """Извлечь resource type из URL ('devices', 'scripts', 'auth', ...)."""
    match = _RESOURCE_RE.search(path)
    return match.group(1) if match else "unknown"


def _extract_resource_id(path: str) -> str | None:
    """Найти первый UUID-сегмент в пути — это resource_id."""
    parts = path.split("/")
    for part in parts:
        if _UUID_RE.fullmatch(part):
            return part
    # Если UUID не найден, попробуем последний непробельный сегмент (может быть числовым ID)
    for part in reversed(parts):
        if part and not part.startswith("v") and part not in SKIP_PATHS:
            # Только если это похоже на ID (не слово вроде "devices")
            if part.isdigit():
                return part
    return None


async def audit_middleware(request: Request, call_next):
    """
    ASGI middleware для автоматического audit logging.

    Запись выполняется ПОСЛЕ отправки ответа клиенту через BackgroundTask.
    Открывает НОВУЮ DB-сессию (не request-сессию) чтобы не зависеть
    от уже завершённой транзакции request.
    """
    if request.method not in AUDITED_METHODS or request.url.path in SKIP_PATHS:
        return await call_next(request)

    start = time.time()
    response: Response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)

    # Логируем только если пользователь аутентифицирован.
    # request.state.principal устанавливается в get_current_user / get_current_principal.
    principal = getattr(request.state, "principal", None)
    if not principal:
        return response

    # Определить user_id по типу principal (User vs APIKey).
    # ВАЖНО: не использовать hasattr() — он вызывает SQLAlchemy дескриптор,
    # который падает с DetachedInstanceError если сессия уже закрыта.
    # isinstance() безопасен — использует Python type system, а не ORM атрибуты.
    from backend.models.user import User as _UserModel
    is_user = isinstance(principal, _UserModel)

    # Читаем значения атрибутов напрямую из __dict__ (без lazy load через дескриптор).
    # Если атрибут expired/detached — получаем None вместо исключения.
    p_vars = vars(principal)
    user_id = p_vars.get("id") if is_user else None
    org_id_val = p_vars.get("org_id")

    # Фиксируем данные ДО возврата response (state может быть очищен)
    audit_data = {
        "org_id": org_id_val,
        "user_id": user_id,
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "action": _path_to_action(request.method, request.url.path),
        "resource_type": _extract_resource_type(request.url.path),
        "resource_id": _extract_resource_id(request.url.path),
        "meta": {
            "status": "success" if response.status_code < 400 else "failure",
            "duration_ms": duration_ms,
            "http_status": response.status_code,
        },
    }

    # КРИТИЧНО: запись в аудит-лог ПОСЛЕ отправки ответа клиенту.
    # BackgroundTask гарантирует порядок выполнения.
    # Открываем НОВУЮ сессию (не request-сессию) — request-транзакция уже закрыта.
    async def _write_audit() -> None:
        async with AsyncSessionLocal() as audit_session:
            try:
                audit_session.add(AuditLog(**audit_data))
                await audit_session.commit()
            except Exception as exc:
                logger.error(
                    "audit_log_write_failed",
                    error=str(exc),
                    action=audit_data.get("action"),
                    org_id=str(audit_data.get("org_id")),
                )

    # Присоединить к response.background (цепочка если уже есть)
    if response.background is not None:
        prev = response.background

        async def _chained() -> None:
            if callable(prev):
                result = prev()
                if inspect.iscoroutine(result):
                    await result
            await _write_audit()

        response.background = BackgroundTask(_chained)
    else:
        response.background = BackgroundTask(_write_audit)

    return response
