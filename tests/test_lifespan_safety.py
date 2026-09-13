"""Startup must work in immutable images and unwind partial startup failures."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.main import app, lifespan


@pytest.mark.parametrize("startup_fails", [False, True])
async def test_lifespan_never_writes_application_files_and_always_cleans_up(startup_fails):
    startup = AsyncMock(side_effect=RuntimeError("isolated startup failure") if startup_fails else None)
    shutdown = AsyncMock()
    with (
        patch("backend.core.startup_checks.check_db_role_not_superuser", AsyncMock()),
        patch("backend.core.lifespan_registry.run_all_startup", startup),
        patch("backend.core.lifespan_registry.run_all_shutdown", shutdown),
        patch.object(Path, "write_text", side_effect=PermissionError("read-only application")),
    ):
        if startup_fails:
            with pytest.raises(RuntimeError, match="isolated startup failure"):
                async with lifespan(app):
                    pytest.fail("must not serve after startup failure")
        else:
            async with lifespan(app):
                startup.assert_awaited_once()
                shutdown.assert_not_awaited()
    shutdown.assert_awaited_once()


async def test_invalid_database_role_is_rejected_before_background_jobs():
    startup = AsyncMock()
    with (
        patch("backend.core.startup_checks.check_db_role_not_superuser",
              AsyncMock(side_effect=RuntimeError("unsafe role"))),
        patch("backend.core.lifespan_registry.run_all_startup", startup),
    ):
        with pytest.raises(RuntimeError, match="unsafe role"):
            async with lifespan(app):
                pytest.fail("must not serve with unsafe role")
    startup.assert_not_awaited()
