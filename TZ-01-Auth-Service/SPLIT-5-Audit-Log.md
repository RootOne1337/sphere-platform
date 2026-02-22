# SPLIT-5 — Audit Log: записать всё, иммутабельно

**ТЗ-родитель:** TZ-01-Auth-Service  
**Ветка:** `stage/1-auth`  
**Задача:** `SPHERE-010`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** —

---

## Цель Сплита

Иммутабельный audit log — все значимые действия записываются автоматически через middleware и декоратор. Нельзя изменить или удалить запись (RLS политики в PostgreSQL).

---

## Шаг 1 — Audit middleware

```python
# backend/middleware/audit.py
import time
import asyncio
import structlog
from fastapi import Request, Response
from starlette.background import BackgroundTask
from backend.database.engine import AsyncSessionLocal
from backend.models.audit_log import AuditLog

logger = structlog.get_logger()

AUDITED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
SKIP_PATHS = {"/health", "/metrics", "/api/v1/auth/refresh", "/api/v1/auth/me"}


async def audit_middleware(request: Request, call_next):
    if request.method not in AUDITED_METHODS or request.url.path in SKIP_PATHS:
        return await call_next(request)

    start = time.time()
    response: Response = await call_next(request)
    duration_ms = int((time.time() - start) * 1000)

    # Логируем только если пользователь аутентифицирован.
    # request.state.principal устанавливается в get_current_user / get_current_api_key.
    principal = getattr(request.state, "principal", None)
    if not principal:
        return response

    # Фиксируем данные ДО возврата response (state может быть очищен).
    audit_data = {
        "org_id":        getattr(principal, "org_id", None),
        "user_id":       principal.id if hasattr(principal, "password_hash") else None,
        "api_key_id":    principal.id if hasattr(principal, "key_hash") else None,
        "ip_address":    request.client.host if request.client else None,
        "action":        f"{request.method.lower()}.{_path_to_action(request.url.path)}",
        "resource_type": _extract_resource_type(request.url.path),
        "resource_id":   _extract_resource_id(request.url.path),
        "status":        "success" if response.status_code < 400 else "failure",
        "duration_ms":   duration_ms,
    }

    # КРИТИЧНО: запись в аудит-лог выполняется ПОСЛЕ отправки ответа клиенту.
    # BackgroundTask гарантирует это — клиент не ждёт INSERT в БД.
    # Открываем НОВУЮ сессию (не request-сессию), чтобы не зависеть
    # от её уже завершённой транзакции.
    async def _write_audit() -> None:
        async with AsyncSessionLocal() as audit_session:
            try:
                audit_session.add(AuditLog(**audit_data))
                await audit_session.commit()
            except Exception as exc:
                logger.error("audit_log_write_failed", error=str(exc), **audit_data)

    # Присоединить к background response.
    # Если response уже имеет background (например, StreamingResponse) — цепочка.
    if response.background is not None:
        prev = response.background
        async def _chained():
            await prev()
            await _write_audit()
        response.background = BackgroundTask(_chained)
    else:
        response.background = BackgroundTask(_write_audit)

    return response
```

> **Почему BackgroundTask, а не `asyncio.ensure_future`:**
> `BackgroundTask` — официальный Starlette механизм: выполняется после того, как
> полный ответ (статус + заголовки + тело) отправлен клиенту. `ensure_future` не
> давал никаких гарантий порядка и замусоривал event loop необработанными задачами
> при ошибках. BackgroundTask также работает корректно в production с несколькими
> Uvicorn workers (каждый worker — свой event loop).
>
> **Почему отдельная сессия, а не request-сессия:**
> К моменту выполнения BackgroundTask транзакция request-сессии (из `get_db()`)
> уже закрыта (commit/rollback). Использовать её небезопасно — открываем свою.

---

## Шаг 2 — Audit Log Service

```python
# backend/services/audit_log_service.py
# Используется для ПРЯМЫХ вызовов из бизнес-логики (не через middleware).
# Middleware использует свой Background механизм — см. Шаг 1.

class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(self, **kwargs) -> None:
        """
        Фиксировать событие в audit_logs в рамках ТЕКУЩЕЙ транзакции.
        Вызывается из сервисного слоя для детальных событий (old_values, new_values).
        Не блокирует API — flush без commit (транзакция закрывается вместе с request).
        Никогда не кидает исключение наружу — ошибки только в stderr.
        """
        try:
            entry = AuditLog(**kwargs)
            self.db.add(entry)
            await self.db.flush()   # отправить INSERT в PG, но не commit
        except Exception as e:
            import structlog
            structlog.get_logger().error("audit_log_failed", error=str(e))

# Использование из сервисного слоя для детальных событий с diff:
# await audit_svc.log(
#     action="device.delete",
#     resource_type="device",
#     resource_id=device_id,
#     old_values={"name": device.name, "status": device.status},
#     status="success",
# )
# → Транзакция закроется вместе с request-сессией (get_db) — без extra-commit.
```

---

## Шаг 3 — Query API

```python
# backend/api/v1/audit.py
@router.get("/audit-logs", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    action: str | None = None,
    resource_type: str | None = None,
    user_id: uuid.UUID | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=100),
    current_user: User = require_permission("monitoring:read"),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AuditLog)
        .where(AuditLog.org_id == current_user.org_id)
        .order_by(AuditLog.timestamp.desc())
    )
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if from_dt:
        stmt = stmt.where(AuditLog.timestamp >= from_dt)
    
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    logs = (await db.execute(stmt)).scalars().all()
    return paginate(logs, page, per_page)
```

---

## Критерии готовности

- [ ] DELETE /devices/{id} → запись в audit_logs автоматически
- [ ] `UPDATE audit_logs SET ...` → ошибка (RLS политика)
- [ ] `DELETE FROM audit_logs` → ошибка (RLS политика)
- [ ] GET /audit-logs фильтрует по action, resource_type, user_id, date range
- [ ] Audit records содержат IP-адрес, user_id/api_key_id
