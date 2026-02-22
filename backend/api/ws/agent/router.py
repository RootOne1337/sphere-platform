# backend/api/ws/agent/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-1 (stub для TZ-08 PC Agent).
# PC Agent использует agent_token (долгоживущий API-ключ), а не JWT.
# Полная реализация обработчиков команд — TZ-08.
#
# TZ-08 SPLIT-5: добавлены обработчики workstation_register, workstation_telemetry.
# FIX 8.1: дублирующий WS endpoint УДАЛЁН — обработка через case в едином handler.
from __future__ import annotations

import json
import asyncio
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.engine import get_db
from backend.database.redis_client import get_redis
from backend.models.api_key import APIKey
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
    from sqlalchemy import select

    key_hash = hashlib.sha256(token.encode()).hexdigest()
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
        # Upsert workstation
        await db.execute(
            text("""
                UPDATE workstations
                SET hostname       = :hostname,
                    os_version     = :os_version,
                    ip_address     = :ip_address,
                    agent_version  = :agent_ver,
                    last_seen      = now()
                WHERE id::text = :wid
            """),
            {
                "wid": workstation_id,
                "hostname": payload.get("hostname", ""),
                "os_version": payload.get("os_version", ""),
                "ip_address": payload.get("ip_address", ""),
                "agent_ver": payload.get("agent_version", ""),
            },
        )

        # Upsert ldplayer_instances
        for inst in payload.get("instances", []):
            await db.execute(
                text("""
                    UPDATE ldplayer_instances
                    SET instance_name = :name,
                        adb_port      = :port,
                        android_serial = :serial
                    WHERE workstation_id::text = :wid
                      AND instance_index = :idx
                """),
                {
                    "wid": workstation_id,
                    "idx": inst["index"],
                    "name": inst["name"],
                    "port": inst["adb_port"],
                    "serial": inst.get("android_serial"),
                },
            )

        await db.commit()

        # Кэшируем топологию в Redis TTL 1h
        try:
            redis = get_redis()
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
        redis = get_redis()
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
                    redis = get_redis()
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
    db: AsyncSession = Depends(get_db),
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
        api_key = await authenticate_agent_token(token, db)
    except ValueError:
        await ws.close(code=4001, reason="invalid_agent_token")
        return

    org_id = str(api_key.org_id)
    session_id = await manager.connect(ws, workstation_id, "pc", org_id)
    logger.info(
        "PC agent connected",
        workstation_id=workstation_id,
        org_id=org_id,
        session=session_id,
    )

    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                await handle_agent_message(workstation_id, org_id, msg, manager, db)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(workstation_id)
        logger.info("PC agent disconnected", workstation_id=workstation_id)
