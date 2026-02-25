# backend/api/ws/android/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-1. Android Agent WebSocket endpoint.
# ВАЖНО: Этот модуль — папка android/router.py (авто-дискавери main.py требует структуру пакета)
from __future__ import annotations

import asyncio
import json

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
from backend.database.redis_client import get_redis_binary
from backend.models.device import Device
from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache
from backend.websocket.connection_manager import ConnectionManager, get_connection_manager

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


async def authenticate_ws_token(token: str, db: AsyncSession):
    """
    Проверить JWT токен или API ключ из first-message WebSocket авторизации.
    Не использует OAuth2 Bearer в URL (безопасно от логирования).

    Возвращает объект с атрибутом org_id (User или _ApiKeyPrincipal).
    """
    import uuid

    import jwt as pyjwt
    from fastapi import HTTPException

    # API key path — токены вида sphr_<env>_<hex>
    if token.startswith("sphr_"):
        from backend.services.api_key_service import APIKeyService
        svc = APIKeyService(db)
        api_key = await svc.authenticate(token)
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or expired API key")

        class _ApiKeyPrincipal:
            def __init__(self, org_id: uuid.UUID) -> None:
                self.org_id = org_id

        return _ApiKeyPrincipal(api_key.org_id)

    # JWT path
    from backend.core.security import decode_access_token
    from backend.models.user import User

    try:
        payload = decode_access_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Проверить blacklist
    from backend.services.cache_service import CacheService
    cache = CacheService()
    if await cache.is_token_blacklisted(payload["jti"]):
        raise HTTPException(status_code=401, detail="Token revoked")

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def handle_agent_message(
    device_id: str,
    org_id: str,
    msg: dict,
    manager: ConnectionManager,
    status_cache: DeviceStatusCache,
) -> None:
    """Обработать входящее текстовое сообщение от Android агента."""
    msg_type = msg.get("type")
    if msg_type == "telemetry":
        await handle_telemetry(device_id, msg, status_cache)
    elif msg_type == "task_progress":
        await handle_task_progress(device_id, org_id, msg)
    elif msg_type == "command_result":
        await handle_command_result(device_id, org_id, msg)
    elif msg_type == "event":
        await handle_device_event(device_id, msg)
    else:
        logger.debug("Unknown message type from android agent", device_id=device_id, type=msg_type)


async def handle_telemetry(
    device_id: str,
    msg: dict,
    status_cache: DeviceStatusCache,
) -> None:
    """Обновить статус устройства из телеметрии."""
    current = await status_cache.get_status(device_id)
    if current:
        if "battery" in msg:
            current.battery = msg["battery"]
        if "cpu" in msg:
            current.cpu_usage = msg["cpu"]
        if "ram_mb" in msg:
            current.ram_usage_mb = msg["ram_mb"]
        if "screen_on" in msg:
            current.screen_on = msg["screen_on"]
        if "vpn_active" in msg:
            current.vpn_active = msg["vpn_active"]
        await status_cache.set_status(device_id, current)


async def handle_task_progress(device_id: str, org_id: str, msg: dict) -> None:
    """Обработать прогресс выполнения DAG от агента."""
    task_id = msg.get("task_id")
    nodes_done = msg.get("nodes_done", 0)
    total_nodes = msg.get("total_nodes", 1)
    current_node = msg.get("current_node", "")
    # For cyclic DAGs: cap progress at 100%, track cycles
    progress = min(int(nodes_done / max(total_nodes, 1) * 100), 100)
    cycles = nodes_done // max(total_nodes, 1)
    logger.debug(
        "task.progress",
        device_id=device_id,
        task_id=task_id,
        nodes_done=nodes_done,
        total_nodes=total_nodes,
        cycles=cycles,
    )
    # Cache progress in Redis for frontend polling
    try:
        from backend.database.redis_client import redis as _redis
        if _redis and task_id:
            import time as _time
            key = f"task_progress:{task_id}"
            # Set started_at only once (first progress message)
            existing_started = await _redis.hget(key, "started_at")
            mapping = {
                "nodes_done": str(nodes_done),
                "total_nodes": str(total_nodes),
                "current_node": current_node,
                "progress": str(progress),
                "cycles": str(cycles),
            }
            if not existing_started:
                mapping["started_at"] = str(_time.time())
            await _redis.hset(key, mapping=mapping)
            await _redis.expire(key, 600)  # TTL 10 min
            # Store live log entry for running task visibility
            import json as _json
            log_entry = _json.dumps({
                "node_id": current_node,
                "nodes_done": nodes_done,
                "ts": _time.time(),
            })
            log_key = f"task_progress_log:{task_id}"
            await _redis.rpush(log_key, log_entry)
            await _redis.ltrim(log_key, -200, -1)  # keep last 200
            await _redis.expire(log_key, 600)
    except Exception:
        pass
    try:
        from backend.websocket.event_publisher import get_event_publisher
        publisher = get_event_publisher()
        if publisher and task_id:
            await publisher.task_progress(
                device_id=device_id,
                org_id=org_id,
                task_id=task_id,
                progress=progress,
            )
    except Exception as e:
        logger.debug("task_progress publish skipped", device_id=device_id, error=str(e))


async def handle_command_result(device_id: str, org_id: str, msg: dict) -> None:
    """Обработать результат команды/задачи от агента."""
    command_id = msg.get("command_id") or msg.get("id")
    if not command_id:
        return
    status = msg.get("status")
    # Publish to Redis result channel (for any waiting HTTP-request polls)
    try:
        from backend.database.redis_client import redis
        if redis:
            result_channel = f"sphere:agent:result:{device_id}:{command_id}"
            await redis.publish(result_channel, json.dumps(msg))
    except Exception as e:
        logger.warning("Failed to publish command result", device_id=device_id, error=str(e))
    # Persist task result to DB on final status (completed or failed)
    if status in ("completed", "failed"):
        result_payload = msg.get("result")
        error_msg = msg.get("error")
        try:
            from backend.database.engine import AsyncSessionLocal
            from backend.services.task_queue import TaskQueue
            from backend.database.redis_client import redis as _redis
            async with AsyncSessionLocal() as db:
                queue = TaskQueue(_redis)
                from backend.services.task_service import TaskService
                svc = TaskService(db=db, queue=queue)
                final_result = result_payload if isinstance(result_payload, dict) else {}
                if error_msg:
                    final_result["error"] = error_msg
                final_result["success"] = (status == "completed")
                await svc.handle_task_result(
                    task_id=command_id,
                    device_id=device_id,
                    result=final_result,
                )
                await db.commit()
        except Exception as e:
            logger.error("Failed to persist task result", command_id=command_id, device_id=device_id, error=str(e))


async def handle_device_event(device_id: str, msg: dict) -> None:
    """Перенаправить событие устройства в fleet events (SPLIT-5)."""
    try:
        from backend.websocket.event_publisher import get_event_publisher
        publisher = get_event_publisher()
        if publisher:
            from backend.schemas.events import EventType, FleetEvent
            await publisher.emit(FleetEvent(
                event_type=EventType.DEVICE_STATUS_CHANGE,
                device_id=device_id,
                org_id=msg.get("org_id", ""),
                payload=msg,
            ))
    except Exception as e:
        logger.debug("Fleet event publish skipped", device_id=device_id, error=str(e))


async def handle_agent_binary(
    device_id: str,
    data: bytes,
    manager: ConnectionManager,
) -> None:
    """Обработать бинарные данные (видеофрейм) от Android агента."""
    try:
        from backend.websocket.stream_bridge import get_stream_bridge
        bridge = get_stream_bridge()
        if bridge:
            await bridge.handle_agent_frame(device_id, data)
    except Exception as e:
        logger.debug("Stream bridge unavailable", device_id=device_id, error=str(e))


@router.websocket("/ws/android/{device_id}")
async def android_agent_ws(
    ws: WebSocket,
    device_id: str,
) -> None:
    await ws.accept()

    manager = get_connection_manager()

    # Redis для status cache (binary — msgpack, не строки)
    redis = await get_redis_binary()
    status_cache = DeviceStatusCache(redis)

    async def _close(code: int, reason: str) -> None:
        """Безопасное закрытие WS — игнорирует double-close RuntimeError."""
        try:
            await ws.close(code=code, reason=reason)
        except Exception:
            pass

    # Шаг 1: First-message auth (НЕ JWT в URL — чтобы не засветить в логах)
    try:
        first_msg = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await _close(4003, "auth_timeout")
        return
    except WebSocketDisconnect:
        return  # Клиент уже отключился — ничего закрывать не нужно
    except Exception:
        await _close(4001, "receive_error")
        return

    token = first_msg.get("token")
    if not token:
        await _close(4001, "no_token")
        return

    # Auth phase: DB session scoped to auth only — not held for WS lifetime
    import uuid

    from fastapi import HTTPException

    org_id_str: str = ""
    try:
        async with AsyncSessionLocal() as db:
            try:
                user = await authenticate_ws_token(token, db)
            except HTTPException:
                await _close(4001, "invalid_token")
                return

            try:
                device_uuid = uuid.UUID(device_id)
            except ValueError:
                await _close(4004, "invalid_device_id")
                return

            device = await db.get(Device, device_uuid)
            if not device or str(device.org_id) != str(user.org_id):
                await _close(4004, "device_not_found")
                return

            org_id_str = str(user.org_id)
    except HTTPException:
        raise
    except Exception:
        await _close(1011, "auth_error")
        return
    # DB session is now CLOSED — safe to enter long-lived WS loop

    session_id = await manager.connect(ws, device_id, "android", org_id_str)
    await status_cache.set_status(device_id, DeviceLiveStatus(
        device_id=device_id,
        status="online",
        ws_session_id=session_id,
    ))

    # Запустить heartbeat (SPLIT-4)
    from backend.websocket.heartbeat import HeartbeatManager
    heartbeat = HeartbeatManager(ws, device_id, status_cache)
    await heartbeat.start()

    # Подписать PubSub router на командный канал этого устройства
    try:
        from backend.websocket.pubsub_router import get_pubsub_router
        pubsub_router = get_pubsub_router()
        if pubsub_router:
            await pubsub_router.subscribe_device(device_id, org_id_str)
    except Exception:
        pass

    # Опубликовать device.online событие (SPLIT-5)
    try:
        from backend.schemas.events import EventType, FleetEvent
        from backend.websocket.event_publisher import get_event_publisher
        publisher = get_event_publisher()
        if publisher:
            await publisher.emit(FleetEvent(
                event_type=EventType.DEVICE_ONLINE,
                device_id=device_id,
                org_id=org_id_str,
                payload={"status": "online", "session_id": session_id},
            ))
    except Exception:
        pass

    # Flush offline command queue — deliver pending commands
    try:
        from backend.websocket.offline_queue import get_offline_queue
        offline_q = get_offline_queue()
        if offline_q:
            await offline_q.flush(
                device_id,
                send_fn=lambda cmd: manager.send_to_device(device_id, cmd),
            )
    except Exception as e:
        logger.debug("Offline queue flush skipped", device_id=device_id, error=str(e))

    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                try:
                    msg = json.loads(data["text"])
                except json.JSONDecodeError:
                    logger.debug("Malformed JSON from agent", device_id=device_id)
                    continue
                try:
                    match msg.get("type"):
                        case "pong":
                            await heartbeat.handle_pong(msg)
                        case "telemetry":
                            await handle_telemetry(device_id, msg, status_cache)
                        case "task_progress":
                            await handle_task_progress(device_id, org_id_str, msg)
                        case "command_result":
                            await handle_command_result(device_id, org_id_str, msg)
                        case "event":
                            await handle_device_event(device_id, msg)
                        case _:
                            # CommandAck from APK has no "type" field — detect by command_id + status
                            if msg.get("command_id") and msg.get("status") in ("completed", "failed", "running", "received"):
                                await handle_command_result(device_id, org_id_str, msg)
                            else:
                                logger.debug(
                                    "Unknown message type",
                                    device_id=device_id,
                                    type=msg.get("type"),
                                )
                except Exception as e:
                    logger.warning(
                        "Error handling agent message",
                        device_id=device_id,
                        msg_type=msg.get("type"),
                        error=str(e),
                    )
            elif "bytes" in data:
                await handle_agent_binary(device_id, data["bytes"], manager)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning("WS receive loop error", device_id=device_id, error=str(e))
    finally:
        await heartbeat.stop()
        await manager.disconnect(device_id)
        await status_cache.mark_offline(device_id)

        # Отписать PubSub router от канала устройства
        try:
            from backend.websocket.pubsub_router import get_pubsub_router
            pubsub_router = get_pubsub_router()
            if pubsub_router:
                await pubsub_router.unsubscribe_device(device_id)
        except Exception:
            pass

        # Опубликовать device.offline событие
        try:
            from backend.schemas.events import EventType, FleetEvent
            from backend.websocket.event_publisher import get_event_publisher
            publisher = get_event_publisher()
            if publisher:
                await publisher.emit(FleetEvent(
                    event_type=EventType.DEVICE_OFFLINE,
                    device_id=device_id,
                org_id=org_id_str,
                    payload={"status": "offline"},
                ))
        except Exception:
            pass
