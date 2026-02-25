# backend/core/logging_config.py
# TZ-11 SPLIT-4: Structlog настройка для всего backend.
#
# FIX 11.2: setup_logging() вызывается на уровне МОДУЛЯ (не через register_startup).
# Причина: при register_startup логи до lifespan (импорт, DI, alembic) теряются.
# Решение: первый `import backend.core.logging_config` → немедленная настройка.
import logging
import sys

import structlog

from backend.core.config import settings


def setup_logging() -> None:
    """
    Настроить structlog + stdlib logging для всего приложения.

    DEV  (DEBUG=True): цветной ConsoleRenderer в stdout.
    PROD (DEBUG=False): JSON renderer — парсится ELK / Loki / любым log aggregator.

    Вызывается один раз при импорте модуля (module-level, внизу файла).
    Повторные вызовы безопасны (structlog.configure идемпотентен).
    """
    shared_processors: list = [
        # Добавляет поля из ContextVar в каждое событие лога
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.DEBUG:
        renderer: structlog.dev.ConsoleRenderer | structlog.processors.JSONRenderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(
        logging.DEBUG if settings.DEBUG else getattr(logging, settings.LOG_LEVEL, logging.INFO)
    )

    # Уменьшить шум от библиотек (уже трекаем HTTP через PrometheusMiddleware)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


# ─── Module-level initialization ─────────────────────────────────────────────
# Немедленная настройка при первом import backend.core.logging_config
# Это гарантирует, что ВСЕ логи с самого старта приложения будут структурированы,
# включая ошибки при инициализации модулей, DI и Alembic migrations.
setup_logging()
