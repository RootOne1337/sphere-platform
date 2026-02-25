# backend/middleware/logging_context.py
# TZ-11 SPLIT-4: Tenant context binding для structlog.
# Используется в endpoint handlers после аутентификации.
import structlog


def bind_user_context(current_user) -> None:
    """
    Привязать org_id и user_id к structlog ContextVar текущего запроса.

    После вызова ВСЕХ последующих logger.xxx() в этом request-контексте
    автоматически включат org_id, user_id, role — без явной передачи.

    Вызывать после get_current_user() в endpoint-handler:

        @router.get("/devices")
        async def list_devices(
            current_user = Depends(get_current_user),
        ):
            bind_user_context(current_user)
            logger.info("Listing devices")  # → {org_id: ..., user_id: ..., role: ...}
    """
    structlog.contextvars.bind_contextvars(
        org_id=str(current_user.org_id),
        user_id=str(current_user.id),
        role=current_user.role,
    )
