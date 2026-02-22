# backend/core/lifespan_registry.py
# CRIT-3: lifespan_registry — решает проблему frozen main.py.
# Каждый модуль регистрирует свои startup/shutdown хуки самостоятельно.
# main.py не меняется при добавлении новых сервисов.
from typing import Callable, Awaitable
import structlog

logger = structlog.get_logger()

_startup_hooks: list[tuple[str, Callable[[], Awaitable[None]]]] = []
_shutdown_hooks: list[tuple[str, Callable[[], Awaitable[None]]]] = []


def register_startup(name: str, coro: Callable[[], Awaitable[None]]) -> None:
    """Зарегистрировать корутину для выполнения при старте FastAPI."""
    _startup_hooks.append((name, coro))


def register_shutdown(name: str, coro: Callable[[], Awaitable[None]]) -> None:
    """Зарегистрировать корутину для выполнения при остановке FastAPI."""
    _shutdown_hooks.append((name, coro))


async def run_all_startup() -> None:
    for name, coro in _startup_hooks:
        logger.info("startup", hook=name)
        await coro()


async def run_all_shutdown() -> None:
    for name, coro in reversed(_shutdown_hooks):  # shutdown в обратном порядке
        logger.info("shutdown", hook=name)
        await coro()
