# backend/schemas/agent_config.py
# ВЛАДЕЛЕЦ: TZ-12 Agent Discovery. Pydantic-схемы для config-эндпоинта.
from __future__ import annotations

from pydantic import BaseModel, Field


class AgentConfigResponse(BaseModel):
    """
    Ответ эндпоинта GET /api/v1/config/agent.

    Агент использует этот конфиг для:
    - Определения актуального server_url
    - Получения feature flags
    - Проверки необходимости обновления (min_agent_version)
    """

    server_url: str = Field(
        description="Актуальный URL бэкенда. Агент использует для WS-подключения.",
    )
    ws_path: str = Field(
        default="/ws/android",
        description="Путь WebSocket эндпоинта.",
    )
    config_version: int = Field(
        default=1,
        description="Версия формата конфига. Агент игнорирует если > поддерживаемой.",
    )
    environment: str = Field(
        default="production",
        description="Текущее окружение сервера.",
    )
    config_poll_interval_seconds: int = Field(
        default=86400,
        description="Рекомендуемый интервал повторного запроса конфига (секунды).",
    )
    features: dict[str, bool] = Field(
        default_factory=dict,
        description="Feature flags для агента.",
    )
    min_agent_version: str = Field(
        default="1.0.0",
        description="Минимальная поддерживаемая версия агента. Ниже — принудительный OTA.",
    )
    enrollment_allowed: bool = Field(
        default=False,
        description="Имеет ли предъявленный API-ключ право на device:register.",
    )
    org_id: str | None = Field(
        default=None,
        description="UUID организации (если аутентифицирован по API-ключу).",
    )
