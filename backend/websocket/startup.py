# backend/websocket/startup.py
# ВЛАДЕЛЕЦ: TZ-03. Регистрация startup/shutdown хуков для всех WS компонентов.
# Импортируется один раз — при импорте main.py через авто-дискавери роутеров.
# CRIT-3: Не трогаем frozen main.py — регистрируем через lifespan_registry.
from __future__ import annotations

from backend.core.lifespan_registry import register_shutdown, register_startup


async def _startup_ws_components() -> None:
    """Инициализировать WS синглтоны после старта Redis."""
    from backend.api.ws.events.router import get_events_manager
    from backend.websocket.connection_manager import get_connection_manager
    from backend.websocket.event_publisher import init_event_publisher
    from backend.websocket.offline_queue import _startup_offline_queue
    from backend.websocket.pubsub_router import get_pubsub_publisher
    from backend.websocket.stream_bridge import init_stream_bridge

    manager = get_connection_manager()
    init_stream_bridge(manager)

    pubsub_publisher = get_pubsub_publisher()
    events_manager = get_events_manager()
    init_event_publisher(pubsub_publisher, events_manager)

    await _startup_offline_queue()
    from backend.core.config import settings
    from backend.websocket.continuous_runtime import start_continuous_runtime
    await start_continuous_runtime(manager, settings.REDIS_URL)
    if settings.DIRECT_TRANSPORT_PROBE_ENABLED:
        from backend.websocket.direct_probe_runtime import start_direct_probe_runtime
        await start_direct_probe_runtime(manager, settings.REDIS_URL)


register_startup("ws_components", _startup_ws_components)


async def _shutdown_ws_components() -> None:
    from backend.websocket.continuous_runtime import stop_continuous_runtime
    from backend.websocket.stream_bridge import get_stream_bridge

    await stop_continuous_runtime()
    from backend.websocket.direct_probe_runtime import stop_direct_probe_runtime
    await stop_direct_probe_runtime()
    bridge = get_stream_bridge()
    if bridge:
        await bridge.close()


register_shutdown("ws_components", _shutdown_ws_components)
