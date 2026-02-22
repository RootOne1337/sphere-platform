# backend/core/cors.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def setup_cors(app: FastAPI) -> None:
    """Настроить CORS. Вызывается при старте приложения."""
    origins = [
        "http://localhost:3000",
        "http://localhost:3002",           # Next.js dev
        "https://adb.leetpc.com",          # Production
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,            # для HTTPOnly cookie (refresh token)
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=3600,                      # Preflight cache 1 час
    )
