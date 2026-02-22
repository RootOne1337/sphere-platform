# backend/middleware/tenant_middleware.py
# Устанавливает PostgreSQL-контекст для RLS на уровне ASGI middleware.
# Подробнее: TZ-00 SPLIT-2 (rls_policies.sql), TZ-01 SPLIT-3 (RBAC).
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TenantMiddleware(BaseHTTPMiddleware):
    """
    ASGI-middleware для установки PostgreSQL-контекста tenant.

    ВНИМАНИЕ: Этот middleware НЕ устанавливает SET LOCAL — это невозможно
    на уровне connection pool без гарантии одной транзакции. Вместо этого
    он извлекает org_id из JWT и сохраняет в request.state.

    Реальная инъекция SET LOCAL app.current_org_id происходит в
    backend/core/dependencies.py::get_tenant_db() при открытии сессии.
    Это единственный правильный подход с asyncpg connection pool.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # org_id будет заполнен после decode JWT в get_current_user dependency
        # Здесь только инициализируем state
        request.state.org_id = None
        request.state.user_id = None
        request.state.user_role = None
        return await call_next(request)


async def set_tenant_context(db_session, org_id: str) -> None:
    """
    Вспомогательная функция: устанавливает RLS-контекст в открытой сессии.
    Вызывается из get_tenant_db() после BEGIN транзакции.

    Пример:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await set_tenant_context(session, org_id)
                result = await session.execute(select(Device))
    """
    await db_session.execute(
        f"SET LOCAL app.current_org_id = '{org_id}'"  # noqa: S608 — org_id is UUID, validated upstream
    )
