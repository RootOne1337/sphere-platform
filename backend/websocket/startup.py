# backend/websocket/startup.py
# ВЛАДЕЛЕЦ: TZ-03. Регистрация startup/shutdown хуков для всех WS компонентов.
# Импортируется один раз — при импорте main.py через авто-дискавери роутеров.
# CRIT-3: Не трогаем frozen main.py — регистрируем через lifespan_registry.
from __future__ import annotations

from backend.core.lifespan_registry import register_startup, register_shutdown


async def _startup_ws_components() -> None:
    """Инициализировать WS синглтоны после старта Redis."""
    from backend.websocket.connection_manager import get_connection_manager
    from backend.websocket.stream_bridge import init_stream_bridge
    from backend.websocket.event_publisher import init_event_publisher
    from backend.websocket.pubsub_router import get_pubsub_publisher
    from backend.api.ws.events.router import get_events_manager

    manager = get_connection_manager()
    init_stream_bridge(manager)

    pubsub_publisher = get_pubsub_publisher()
    events_manager = get_events_manager()
    init_event_publisher(pubsub_publisher, events_manager)


register_startup("ws_components", _startup_ws_components)
