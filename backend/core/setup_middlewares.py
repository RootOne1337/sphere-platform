# backend/core/setup_middlewares.py
# ВЛАДЕЛЕЦ: TZ-00 infrastructure + TZ-этапы добавляют сюда свои middleware.
# Вызывается один раз из backend/core/cors.py::setup_cors() при старте приложения.
# main.py — заморожен, новые middleware регистрируются ТОЛЬКО здесь.
#
# ПОРЯДОК ВАЖЕН: Starlette применяет middleware в обратном порядке регистрации
# (LIFO stack). Последний добавленный = innermost (ближайший к роутерам).
# Типичный порядок вызовов: request → CORS → TenantMiddleware → AuditMiddleware → routes
from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware


def setup_all_middlewares(app: FastAPI) -> None:
    """
    Зарегистрировать все domain-middlewares.
    Вызывается из setup_cors() — ПОСЛЕ добавления CORSMiddleware,
    чтобы audit/tenant middleware оказались внутри (LIFO).
    """
    # ── TZ-00: TenantMiddleware ─────────────────────────────────────────────
    # Инициализирует request.state (org_id, user_id, user_role).
    # Реальный RLS-контекст устанавливается в get_tenant_db() dependency.
    from backend.middleware.tenant_middleware import TenantMiddleware
    app.add_middleware(TenantMiddleware)

    # ── TZ-01 SPLIT-5: Audit middleware ─────────────────────────────────────
    # Пишет AuditLog для всех мутирующих запросов (POST/PUT/PATCH/DELETE).
    # КРИТИЧНО: должен быть innermost (последним добавленным) — читает
    # request.state.principal ПОСЛЕ того, как route handler его установил.
    from backend.middleware.audit import audit_middleware
    app.add_middleware(BaseHTTPMiddleware, dispatch=audit_middleware)
