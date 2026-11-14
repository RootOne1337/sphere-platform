# backend/middleware/tenant_middleware.py
# Инициализация request state. Контекст БД задаётся отдельно в tenant-bound Session.
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Инициализирует request state; не декодирует JWT и не устанавливает DB context.
    PostgreSQL LOCAL context восстанавливает backend.database.tenant для явно
    привязанных Session. Middleware не обеспечивает RLS для unscoped callers.
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
    Совместимый helper: привязывает Session к tenant на всех её транзакциях.

    Пример:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await set_tenant_context(session, org_id)
                result = await session.execute(select(Device))
    """
    from backend.database.tenant import bind_tenant_context

    await bind_tenant_context(db_session, org_id)
