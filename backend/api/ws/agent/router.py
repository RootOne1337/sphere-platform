# backend/api/ws/agent/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-1 (stub для TZ-08 PC Agent).
# PC Agent использует agent_token (долгоживущий API-ключ), а не JWT.
# Полная реализация обработчиков команд — TZ-08.
#
# TZ-08 SPLIT-5: добавлены обработчики workstation_register, workstation_telemetry.
# FIX 8.1: дублирующий WS endpoint УДАЛЁН — обработка через case в едином handler.
from __future__ import annotations

import asyncio
import json
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import AsyncSessionLocal
from backend.database.redis_client import get_redis
from backend.models.api_key import APIKey
from backend.models.workstation import Workstation
from backend.websocket.connection_manager import ConnectionManager, get_connection_manager

logger = structlog.get_logger()

router = APIRouter(tags=["websocket"])


async def authenticate_agent_token(token: str, db: AsyncSession) -> APIKey:
    """
    Проверяет agent_token из first-message.
    agent_token = sha256(raw_key) хранится в таблице api_keys с type='agent'.
    Отличие от JWT: не истекает через 15 мин, не нужен refresh-цикл.
    """
    import hashlib
    from datetime import datetime, timezone

    from sqlalchemy import select

    key_hash = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.is_active == True,  # noqa: E712
            APIKey.type == "agent",
        )
    )
    api_key = result.scalar_one_or_none()
    if not api_key:
        raise ValueError("Invalid or inactive agent token")
    if "device:register" not in api_key.permissions:
        raise ValueError("Agent registration permission required")
    # F-04: проверка срока действия токена
    if api_key.expires_at is not None and api_key.expires_at < now:
        raise ValueError("Agent token has expired")
    return api_key


async def handle_workstation_register(
    workstation_id: str,
    payload: dict,
    org_id: str,
    db: AsyncSession,
) -> None:
    """
    TZ-08 SPLIT-5: Upsert воркстанции + инстансов при регистрации агента.
    Кэширует топологию в Redis TTL 1h.
    """
    try:
        from datetime import datetime, timezone

        from backend.models.ldplayer_instance import LDPlayerInstance
        workstation = await db.scalar(select(Workstation).where(
            Workstation.id == uuid.UUID(workstation_id), Workstation.org_id == uuid.UUID(org_id),
        ))
        if workstation is None:
            raise ValueError("Workstation not found")
        workstation.hostname = payload.get("hostname", "")
        workstation.os_version = payload.get("os_version", "")
        workstation.agent_version = payload.get("agent_version", "")
        workstation.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
        workstation.is_online = True
        workstation.meta = {**(workstation.meta or {}), "ip_address": payload.get("ip_address", "")}
        for inst in payload.get("instances", []):
            instance = await db.scalar(select(LDPlayerInstance).where(
                LDPlayerInstance.workstation_id == workstation.id,
                LDPlayerInstance.org_id == workstation.org_id,
                LDPlayerInstance.instance_index == inst["index"],
            ))
            if instance:
                instance.android_serial = inst.get("android_serial")
                instance.meta = {**(instance.meta or {}), "name": inst.get("name"), "adb_port": inst.get("adb_port")}

        await db.commit()

        # Кэшируем топологию в Redis TTL 1h
        try:
            redis = await get_redis()
            if redis:
                topology_key = f"topology:workstation:{workstation_id}"
                await redis.setex(topology_key, 3600, json.dumps(payload))
        except Exception as exc:
            logger.warning("Redis topology cache failed", error=str(exc))

        logger.info(
            "Workstation registered",
            workstation_id=workstation_id,
            instances=len(payload.get("instances", [])),
        )
    except Exception as exc:
        logger.error(
            "workstation_register error",
            workstation_id=workstation_id,
            error=str(exc),
        )
        await db.rollback()


async def handle_workstation_telemetry(
    workstation_id: str,
    payload: dict,
    org_id: str,
) -> None:
    """
    TZ-08 SPLIT-3: Сохранить телеметрию воркстанции в Redis TTL 120s.
    FIX 8.1: обработка здесь, в едином WS handler — не в отдельном endpoint.
    """
    try:
        redis = await get_redis()
        if redis:
            key = f"workstation:telemetry:{workstation_id}"
            await redis.setex(key, 120, json.dumps(payload))
            # Публикуем событие для дашборда
            await redis.publish(
                f"sphere:org:events:{org_id}",
                json.dumps({"type": "workstation_telemetry", "data": payload}),
            )
    except Exception as exc:
        logger.warning(
            "Failed to store workstation telemetry",
            workstation_id=workstation_id,
            error=str(exc),
        )


async def handle_agent_message(
    workstation_id: str,
    org_id: str,
    msg: dict,
    manager: ConnectionManager,
    db: AsyncSession,
) -> None:
    """
    Обработать входящее сообщение от PC агента.
    TZ-08 SPLIT-2/3/5: полная маршрутизация по type.
    """
    msg_type = msg.get("type")

    match msg_type:
        case "command_result":
            command_id = msg.get("command_id") or msg.get("id")
            if command_id:
                try:
                    redis = await get_redis()
                    if redis:
                        channel = f"sphere:agent:result:{workstation_id}:{command_id}"
                        await redis.publish(channel, json.dumps(msg))
                except Exception as exc:
                    logger.warning(
                        "Failed to publish PC agent command result",
                        workstation_id=workstation_id,
                        error=str(exc),
                    )

        case "workstation_register":
            payload = msg.get("payload", {})
            await handle_workstation_register(workstation_id, payload, org_id, db)

        case "workstation_telemetry":
            payload = msg.get("payload", {})
            await handle_workstation_telemetry(workstation_id, payload, org_id)

        case _:
            logger.debug(
                "PC agent message",
                workstation_id=workstation_id,
                type=msg_type,
            )


@router.websocket("/ws/agent/{workstation_id}")
async def pc_agent_ws(
    ws: WebSocket,
    workstation_id: str,
) -> None:
    await ws.accept()

    manager = get_connection_manager()

    # First-message auth с agent_token
    try:
        first_msg = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
    except asyncio.TimeoutError:
        await ws.close(code=4003, reason="auth_timeout")
        return
    except Exception:
        await ws.close(code=4001, reason="receive_error")
        return

    token = first_msg.get("token")
    if not token:
        await ws.close(code=4001, reason="no_token")
        return

    try:
        async with AsyncSessionLocal() as db:
            api_key = await authenticate_agent_token(token, db)
            workstation = await db.scalar(select(Workstation).where(
                Workstation.id == uuid.UUID(workstation_id),
                Workstation.org_id == api_key.org_id,
            ))
            if workstation is None:
                await ws.close(code=4004, reason="workstation_not_found")
                return
            org_id = str(api_key.org_id)
    except ValueError:
        await ws.close(code=4001, reason="invalid_agent_token")
        return

    session_id = await manager.connect(ws, workstation_id, "pc", org_id)
    logger.info(
        "PC agent connected",
        workstation_id=workstation_id,
        org_id=org_id,
        session=session_id,
    )

    pubsub = None
    try:
        from backend.websocket.pubsub_router import get_pubsub_router
        pubsub = get_pubsub_router()
        if pubsub:
            await pubsub.subscribe_device(workstation_id, org_id)
        while True:
            data = await ws.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                async with AsyncSessionLocal() as db:
                    await handle_agent_message(workstation_id, org_id, msg, manager, db)
    except WebSocketDisconnect:
        pass
    finally:
        disconnected = await manager.disconnect(workstation_id, session_id=session_id)
        if disconnected and pubsub:
            await pubsub.unsubscribe_device(workstation_id)
        logger.info("PC agent disconnected", workstation_id=workstation_id)
