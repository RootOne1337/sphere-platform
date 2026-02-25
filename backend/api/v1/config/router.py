# backend/api/v1/config/router.py
# ВЛАДЕЛЕЦ: TZ-12 Agent Discovery. Конфигурация для агентов (zero-touch provisioning).
# Авто-дискавери: main.py подключает backend/api/v1/config/router.py автоматически.
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.schemas.agent_config import AgentConfigResponse
from backend.services.api_key_service import APIKeyService

router = APIRouter(prefix="/config", tags=["config"])
logger = logging.getLogger(__name__)

# Ключ для Redis-кэша agent-config
_REDIS_CACHE_KEY = "agent_config:{env}"


def _load_agent_config_from_file() -> dict[str, Any]:
    """
    Загружает agent-config из файла agent-config/environments/{env}.json.

    Fallback: если файл не найден — возвращает пустой dict
    (эндпоинт продолжит работу с базовыми значениями из Settings).
    """
    env = settings.AGENT_CONFIG_ENV or settings.ENVIRONMENT
    config_dir = Path(settings.AGENT_CONFIG_DIR)

    # Поддержка относительных путей (от корня проекта)
    if not config_dir.is_absolute():
        # Определяем корень проекта: backend/../ или cwd
        project_root = Path(__file__).resolve().parents[4]  # api/v1/config/router.py → корень
        config_dir = project_root / config_dir

    config_file = config_dir / "environments" / f"{env}.json"
    if not config_file.exists():
        logger.warning("Agent config файл не найден: %s", config_file)
        return {}

    try:
        return json.loads(config_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Ошибка чтения agent config %s: %s", config_file, exc)
        return {}


async def _get_cached_agent_config(redis: Any) -> dict[str, Any] | None:
    """Получает agent-config из Redis-кэша (если TTL > 0 и кэш валиден)."""
    if settings.AGENT_CONFIG_CACHE_TTL <= 0 or redis is None:
        return None
    cache_key = _REDIS_CACHE_KEY.format(env=settings.AGENT_CONFIG_ENV or settings.ENVIRONMENT)
    try:
        cached = await redis.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        logger.debug("Redis cache miss/error для agent config")
    return None


async def _set_cached_agent_config(redis: Any, data: dict[str, Any]) -> None:
    """Сохраняет agent-config в Redis-кэш с TTL."""
    if settings.AGENT_CONFIG_CACHE_TTL <= 0 or redis is None:
        return
    cache_key = _REDIS_CACHE_KEY.format(env=settings.AGENT_CONFIG_ENV or settings.ENVIRONMENT)
    try:
        await redis.set(cache_key, json.dumps(data), ex=settings.AGENT_CONFIG_CACHE_TTL)
    except Exception:
        logger.debug("Не удалось записать agent config в Redis cache")


@router.get(
    "/agent",
    response_model=AgentConfigResponse,
    summary="Конфигурация для агента (zero-touch provisioning)",
    description=(
        "Возвращает актуальный конфиг для Android/PC агента. "
        "Загружает настройки из agent-config/environments/{env}.json с Redis-кэшированием. "
        "Аутентификация по X-API-Key (enrollment или device key) — опционально. "
        "Агент вызывает этот эндпоинт при первом запуске и периодически "
        "для обнаружения смены server_url."
    ),
)
async def get_agent_config(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_agent_fingerprint: str | None = Header(default=None, alias="X-Agent-Fingerprint"),
    db: AsyncSession = Depends(get_db),
    redis: Any = Depends(get_redis),
) -> AgentConfigResponse:
    """
    Конфиг-эндпоинт для агентов.

    Логика загрузки конфигурации:
    1. Redis-кэш (если TTL > 0)
    2. Файл agent-config/environments/{env}.json
    3. Fallback на значения из Settings

    Логика аутентификации (мягкая — enrollment key или device key):
    - Если X-API-Key передан и валиден → org-scoped обогащение
    - Если нет ключа → базовый конфиг с enrollment_api_key для bootstrap
    """
    from fastapi import HTTPException, status

    # Загружаем конфиг из кэша или файла
    file_config = await _get_cached_agent_config(redis)
    if file_config is None:
        file_config = _load_agent_config_from_file()
        if file_config:
            await _set_cached_agent_config(redis, file_config)

    # Определяем server_url (приоритет: файл → Settings)
    server_url = (
        file_config.get("server_url", "").strip().rstrip("/")
        or settings.SERVER_PUBLIC_URL.rstrip("/")
    )

    # Features из файла или дефолтные
    file_features = file_config.get("features", {})
    features = {
        "telemetry_enabled": file_features.get("telemetry_enabled", True),
        "streaming_enabled": file_features.get("streaming_enabled", True),
        "ota_enabled": file_features.get("ota_enabled", settings.ENVIRONMENT != "development"),
        "auto_register": file_features.get("auto_register", True),
    }

    env = file_config.get("environment") or settings.ENVIRONMENT

    # Enrollment API key для агентов (позволяет zero-touch регистрацию)
    enrollment_api_key = file_config.get("enrollment_api_key")

    base_config = AgentConfigResponse(
        server_url=server_url,
        ws_path=file_config.get("ws_path", "/ws/android"),
        config_version=file_config.get("config_version", 1),
        environment=env,
        config_poll_interval_seconds=file_config.get("config_poll_interval_seconds", 86400),
        features=features,
        min_agent_version=file_config.get("min_agent_version", "1.0.0"),
        enrollment_api_key=enrollment_api_key,
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
