# backend/tasks/orchestration_loop.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# Фоновая задача: OrchestrationEngine — автоматические регистрации, фарм, мониторинг банов.
# Регистрируется через lifespan_registry при старте сервера.
# Считывает настройки из БД (pipeline_settings) → выживает после перезагрузки.
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def _startup_orchestration_engine() -> None:
    """Запуск фонового движка оркестрации."""
    from backend.services.orchestrator.orchestration_engine import OrchestrationEngine

    engine = OrchestrationEngine()
    asyncio.create_task(engine.start())
    logger.info("orchestration_engine.registered")


# ── Авторегистрация через lifespan_registry ──────────────────────────────────

from backend.core.lifespan_registry import register_startup  # noqa: E402

register_startup("orchestration_engine", _startup_orchestration_engine)
