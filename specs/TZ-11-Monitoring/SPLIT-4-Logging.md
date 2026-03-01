# SPLIT-4 — Structured Logging (structlog + JSON)

**ТЗ-родитель:** TZ-11-Monitoring  
**Ветка:** `stage/11-monitoring`  
**Задача:** `SPHERE-059`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Зависит от:** TZ-11 SPLIT-1 (Prometheus)

---

## Цель Сплита

Настройка structlog для всего backend: JSON формат в production, human-readable в dev. Контекстный логинг (org_id, device_id, request_id). Интеграция с Prometheus для подсчёта ошибок.

---

## Шаг 1 — structlog настройка

```python
# backend/core/logging_config.py
import structlog
import logging
import sys
from backend.core.config import settings

def setup_logging():
    """
    Настроить structlog для всего приложения.
    Вызывается при старте (lifespan или module-level).
    
    DEV:  цветной human-readable вывод в консоль
    PROD: JSON формат для сбора в ELK/Loki
    """
    
    shared_processors = [
        structlog.contextvars.merge_contextvars,   # request_id, org_id из ContextVar
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    
    if settings.DEBUG:
        # DEV: цветной вывод
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        # PROD: JSON
        renderer = structlog.processors.JSONRenderer()
    
    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    # Стандартный logging → structlog formatter
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
    root_logger.setLevel(logging.INFO if not settings.DEBUG else logging.DEBUG)
    
    # Уменьшить шум от библиотек
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DEBUG else logging.WARNING
    )
```

---

## Шаг 2 — Request ID Middleware

```python
# backend/middleware/request_id.py
import uuid
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Добавить X-Request-ID в каждый запрос.
    structlog ContextVar гарантирует, что все логи в рамках запроса
    содержат одинаковый request_id.
    """
    
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(
            "X-Request-ID", str(uuid.uuid4())[:8]
        )
        
        # Привязать контекст к текущему запросу
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        
        return response
```

---

## Шаг 3 — Tenant Context в логах

```python
# backend/middleware/logging_context.py
from backend.core.dependencies import get_current_user
import structlog

async def bind_user_context(current_user):
    """
    Привязать org_id и user_id к structlog контексту.
    Вызывается после аутентификации в endpoint.
    
    Использование в endpoint:
        @router.get("/devices")
        async def list_devices(
            current_user = Depends(get_current_user),
        ):
            bind_user_context(current_user)
            logger.info("Listing devices")  # автоматически включает org_id, user_id
    """
    structlog.contextvars.bind_contextvars(
        org_id=str(current_user.org_id),
        user_id=str(current_user.id),
        role=current_user.role,
    )
```

---

## Шаг 4 — Примеры использования

```python
# backend/services/device_service.py
import structlog

logger = structlog.get_logger()

class DeviceService:
    async def create_device(self, device_data: dict):
        logger.info(
            "Creating device",
            device_id=device_data["id"],
            device_type=device_data["type"],
        )
        
        try:
            device = Device(**device_data)
            self.db.add(device)
            await self.db.flush()
            
            logger.info(
                "Device created",
                device_id=device.id,
                # org_id и request_id добавляются автоматически из ContextVar
            )
            return device
        except Exception as e:
            logger.error(
                "Device creation failed",
                device_id=device_data.get("id"),
                error=str(e),
                exc_info=True,   # включить stack trace
            )
            raise
```

**Пример JSON лога (production):**

```json
{
  "event": "Device created",
  "level": "info",
  "timestamp": "2026-02-21T22:00:00.000Z",
  "logger": "backend.services.device_service",
  "request_id": "a1b2c3d4",
  "org_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "660e9400-f39c-51e5-b826-557766550000",
  "role": "org_admin",
  "device_id": "ld:0",
  "method": "POST",
  "path": "/api/v1/devices"
}
```

---

## Шаг 5 — Error Counter для Prometheus

```python
# backend/core/logging_config.py — добавить в processors
from backend.metrics import auth_attempts_total  # пример

class PrometheusErrorCounter:
    """
    structlog processor: инкрементирует Prometheus counter при ERROR/CRITICAL логах.
    """
    def __call__(self, logger, method_name, event_dict):
        if method_name in ("error", "critical", "exception"):
            from backend.metrics import http_requests_total
            # Общий счётчик ошибок в логах
            # (Отдельная метрика от HTTP 5xx — покрывает background task ошибки)
        return event_dict
```

---

## Шаг 6 — Lifespan Integration

```python
# backend/core/logging_config.py — в конце файла
#
# FIX 11.2: БЫЛО — setup_logging() через register_startup (async, в lifespan)
#   → Ошибки ДО lifespan (импорт модулей, DI, alembic) НЕ логировались!
#   → Только стандартный Python logging без структуры
#
# СТАЛО — вызов на уровне модуля (module-level, синхронный)
# Срабатывает при ПЕРВОМ import backend.core.logging_config
# ─ т.е. ДО lifespan, ДО DI, ДО роутеров

setup_logging()  # <- Немедленная инициализация при импорте
```

---

## Стратегия тестирования

### Пример unit-теста

```python
import structlog
from backend.core.logging_config import setup_logging

def test_json_logging_format(capsys):
    """В production режиме логи должны быть JSON."""
    setup_logging()
    logger = structlog.get_logger()
    
    structlog.contextvars.bind_contextvars(request_id="test123")
    logger.info("Test event", key="value")
    
    captured = capsys.readouterr()
    import json
    log_entry = json.loads(captured.out)
    
    assert log_entry["event"] == "Test event"
    assert log_entry["request_id"] == "test123"
    assert log_entry["key"] == "value"
```

---

## Критерии готовности

- [ ] DEV: цветной human-readable вывод в консоль
- [ ] PROD: JSON формат (парсится ELK/Loki)
- [ ] `X-Request-ID` header добавляется ко всем ответам
- [ ] Все логи содержат: `request_id`, `timestamp`, `level`
- [ ] После auth: логи содержат `org_id`, `user_id`, `role`
- [ ] `logger.error()` → stack trace включён (`exc_info=True`)
- [ ] Uvicorn access логи подавлены (не дублируются с PrometheusMiddleware)
