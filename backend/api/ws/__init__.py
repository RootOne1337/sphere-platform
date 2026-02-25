# backend/api/ws/__init__.py
# Импорт при первом обращении к пакету — регистрирует PubSub и WS startup хуки.
# main.py импортирует каждый router.py, что вызывает этот __init__.py первым.
import backend.websocket.pubsub_router  # noqa: F401 — регистрирует startup/shutdown хуки
import backend.websocket.startup  # noqa: F401 — регистрирует ws_components startup хук
