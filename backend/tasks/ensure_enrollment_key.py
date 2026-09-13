"""Provision only the configured enrollment identity during development startup."""

from __future__ import annotations

import structlog

from backend.core.lifespan_registry import register_startup
from backend.services.enrollment_bootstrap import (
    BootstrapOrganizationMissing,
    EnrollmentConfigurationError,
    EnrollmentKeyConflict,
    ensure_configured_enrollment_key,
)

logger = structlog.get_logger()


async def _ensure_enrollment_key() -> None:
    from backend.core.config import settings

    if settings.ENVIRONMENT not in ("development", "dev", "local"):
        return

    try:
        key_id, org_id = await ensure_configured_enrollment_key()
    except (BootstrapOrganizationMissing, EnrollmentKeyConflict, EnrollmentConfigurationError) as exc:
        # Keep the API available to repair bootstrap configuration. The explicit
        # CLI remains strict; database outages/unexpected errors still propagate.
        # Do not serialize the exception, config, raw key, prefix or hash.
        logger.warning("enrollment_bootstrap_unavailable", reason=type(exc).__name__,
            action="Run the enrollment bootstrap CLI with the selected operator organization")
        return
    logger.info("enrollment_bootstrap_ready", key_id=str(key_id), org_id=str(org_id))


register_startup("ensure_enrollment_key", _ensure_enrollment_key)
