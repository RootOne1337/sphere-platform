# backend/core/cors.py
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_cors(app: FastAPI) -> None:
    """Настроить CORS и зарегистрировать domain-middlewares. Вызывается при старте приложения."""
    origins = [
        "http://localhost:3000",
        "http://localhost:3002",           # Next.js dev
    ]
    # Дополнительные origins из переменной окружения (через запятую)
    extra = os.environ.get("CORS_EXTRA_ORIGINS", "")
    if extra:
        origins.extend(o.strip() for o in extra.split(",") if o.strip())

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,            # для HTTPOnly cookie (refresh token)
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Refresh-Token"],
        expose_headers=["X-Request-ID"],
        max_age=3600,                      # Preflight cache 1 час
    )

    # Регистрация domain-middlewares (TenantMiddleware, AuditMiddleware, и т.д.)
    # Добавляются ПОСЛЕ CORS — оказываются innermost в LIFO-стеке Starlette.
    from backend.core.setup_middlewares import setup_all_middlewares
    setup_all_middlewares(app)
