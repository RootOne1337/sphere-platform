# backend/api/v1/config/router.py
# ВЛАДЕЛЕЦ: TZ-12 Agent Discovery. Конфигурация для агентов (zero-touch provisioning).
# Авто-дискавери: main.py подключает backend/api/v1/config/router.py автоматически.
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.database.engine import get_db
from backend.schemas.agent_config import AgentConfigResponse
from backend.services.api_key_service import APIKeyService

router = APIRouter(prefix="/config", tags=["config"])


@router.get(
    "/agent",
    response_model=AgentConfigResponse,
    summary="Конфигурация для агента (zero-touch provisioning)",
    description=(
        "Возвращает актуальный конфиг для Android/PC агента. "
        "Аутентификация по X-API-Key (enrollment или device key). "
        "Агент вызывает этот эндпоинт при первом запуске и периодически "
        "для обнаружения смены server_url."
    ),
)
async def get_agent_config(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_agent_fingerprint: str | None = Header(default=None, alias="X-Agent-Fingerprint"),
    db: AsyncSession = Depends(get_db),
) -> AgentConfigResponse:
    """
    Конфиг-эндпоинт для агентов.

    Логика аутентификации (мягкая — enrollment key или device key):
    - Если X-API-Key передан и валиден → org-scoped конфиг
    - Если нет ключа → базовый конфиг (server_url + версия)

    Агент использует этот эндпоинт для:
    1. Обнаружения актуального server_url при первом запуске (BuildConfig.CONFIG_URL)
    2. Периодической проверки смены server_url (poll раз в сутки)
    3. Получения feature flags
    """
    from fastapi import HTTPException, status

    # Определяем окружение
    env = settings.ENVIRONMENT

    # Базовый конфиг (без аутентификации — для bootstrap)
    base_config = AgentConfigResponse(
        server_url=_get_server_url(),
        ws_path="/ws/android",
        config_version=1,
        environment=env,
        config_poll_interval_seconds=86400,
        features={
            "telemetry_enabled": True,
            "streaming_enabled": True,
            "ota_enabled": env != "development",
            "auto_register": True,
        },
        min_agent_version="1.0.0",
    )

    # Если API key передан — проверяем и обогащаем конфиг
    if x_api_key:
        api_key_svc = APIKeyService(db)
        key = await api_key_svc.authenticate(x_api_key)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Невалидный или истёкший API-ключ",
            )
        # enrollment key — возвращаем enrollment_allowed
        base_config.enrollment_allowed = "device:register" in (key.permissions or [])
        base_config.org_id = str(key.org_id)

    return base_config


def _get_server_url() -> str:
    """
    Определяет актуальный server_url на основе окружения.

    В production/staging — из переменной окружения SERVER_PUBLIC_URL.
    В development — http://10.0.2.2:8000 (Android эмулятор loopback).
    """
    import os

    public_url = os.environ.get("SERVER_PUBLIC_URL", "").strip()
    if public_url:
        return public_url.rstrip("/")

    if settings.ENVIRONMENT == "development":
        return "http://10.0.2.2:8000"

    # Fallback: что-то разумное
    return "http://localhost:8000"
