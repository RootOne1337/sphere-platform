# backend/services/audit_log_service.py
# ВЛАДЕЛЕЦ: TZ-01 SPLIT-5. Прямые вызовы из бизнес-логики для детальных событий.
# Middleware автоматически пишет для HTTP-запросов — см. backend/middleware/audit.py.
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit_log import AuditLog

logger = structlog.get_logger()


class AuditLogService:
    """
    Фиксировать события в audit_logs в рамках ТЕКУЩЕЙ транзакции.
    Используется из сервисного слоя для детальных событий с diff (old/new values).
    Не блокирует API — flush без commit (транзакция закрывается вместе с request).
    Никогда не поднимает исключение — ошибки только в stderr.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(
        self,
        action: str,
        *,
        org_id=None,
        user_id=None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        status: str = "success",
        duration_ms: int | None = None,
    ) -> None:
        """
        Записать audit event.
        status и duration_ms хранятся в поле meta (модель не имеет отдельных колонок для них).
        """
        try:
            meta: dict = {"status": status}
            if duration_ms is not None:
                meta["duration_ms"] = duration_ms

            entry = AuditLog(
                org_id=org_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id is not None else None,
                ip_address=ip_address,
                user_agent=user_agent,
                old_value=old_values,
                new_value=new_values,
                meta=meta,
            )
            self.db.add(entry)
            await self.db.flush()
        except Exception as exc:
            logger.error(
                "audit_log_failed",
                error=str(exc),
                action=action,
                org_id=str(org_id) if org_id else None,
                user_id=str(user_id) if user_id else None,
            )
