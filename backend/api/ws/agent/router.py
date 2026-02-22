# backend/api/ws/agent/router.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-1 (stub для TZ-08 PC Agent).
# PC Agent использует agent_token (долгоживущий API-ключ), а не JWT.
# Полная реализация обработчиков команд — TZ-08.
from __future__ import annotations

import json
import asyncio

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
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


async def handle_agent_message(
    workstation_id: str,
    msg: dict,
    manager: ConnectionManager,
) -> None:
    """Обработать входящее сообщение от PC агента. Полная реализация — TZ-08."""
    msg_type = msg.get("type")
    if msg_type == "command_result":
        command_id = msg.get("command_id") or msg.get("id")
        if command_id:
            try:
                from backend.database.redis_client import redis
                if redis:
                    result_channel = f"sphere:agent:result:{workstation_id}:{command_id}"
                    await redis.publish(result_channel, json.dumps(msg))
            except Exception as e:
                logger.warning(
                    "Failed to publish PC agent command result",
                    workstation_id=workstation_id,
                    error=str(e),
                )
    else:
        logger.debug("PC agent message", workstation_id=workstation_id, type=msg_type)


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

    session_id = await manager.connect(ws, workstation_id, "pc", str(api_key.org_id))
    logger.info(
        "PC agent connected",
        workstation_id=workstation_id,
        org_id=str(api_key.org_id),
        session=session_id,
    )

    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                msg = json.loads(data["text"])
                await handle_agent_message(workstation_id, msg, manager)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(workstation_id)
        logger.info("PC agent disconnected", workstation_id=workstation_id)
