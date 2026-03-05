# -*- coding: utf-8 -*-
"""
Mock-сервер Sphere Platform для интеграционного и нагрузочного тестирования.

Эмулирует REST API и WebSocket endpoint реального бэкенда,
полностью совместимый с протоколом Android-агента (router.py + heartbeat.py).

Протокол:
  • POST /api/v1/devices/register — регистрация устройств
  • POST /api/v1/vpn/assign — VPN enrollment
  • GET  /api/v1/vpn/status — статус VPN
  • GET  /api/v1/devices/{device_id} — информация об устройстве
  • WS   /ws/android/{device_id} — WebSocket:
        - First-message auth (JWT / API-key)
        - Серверный ping с полем `ts` (time.time()) каждые 30s
        - Noop keepalive каждые 10s (Cloudflare tunnel fix)
        - EXECUTE_DAG (реальный формат с command_id, signed_at, ttl, payload.dag)
        - Приём: pong (с echo ts + телеметрия), CommandAck (без «type»!),
          task_progress, command_result, telemetry
        - CANCEL_DAG, PAUSE_DAG, RESUME_DAG
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("mock_server")

# ---------------------------------------------------------------------------
# In-memory state
# ---------------------------------------------------------------------------

_devices: dict[str, dict[str, Any]] = {}
_vpn_assignments: dict[str, str] = {}  # device_id → ip
_vpn_counter: int = 0
_ws_connections: dict[str, WebSocket] = {}

# Трекинг результатов (аналог Redis-кеша в бэкенде)
_task_results: dict[str, dict[str, Any]] = {}
_task_progress: dict[str, dict[str, Any]] = {}
_command_acks: dict[str, str] = {}  # command_id → status

# ---------------------------------------------------------------------------
# Настройки сервера (совпадают с реальным бэкендом)
# ---------------------------------------------------------------------------

HEARTBEAT_INTERVAL = 30.0          # серверный ping каждые 30s (heartbeat.py)
NOOP_INTERVAL = 10.0               # noop keepalive каждые 10s (router.py)
TASK_SEND_DELAY = 5.0              # задержка перед первой отправкой task
TASK_SEND_INTERVAL_MIN = 15.0      # минимальный интервал между задачами
TASK_SEND_INTERVAL_MAX = 45.0      # максимальный интервал
TASK_SEND_PROBABILITY = 0.4        # вероятность отправки задачи
HEARTBEAT_TIMEOUT = 15.0           # таймаут после пропущенного pong

# ---------------------------------------------------------------------------
# Загрузка DAG-фикстур
# ---------------------------------------------------------------------------

_DAG_FIXTURES: list[dict[str, Any]] = []


def _load_dag_fixtures() -> None:
    """Загрузить DAG-фикстуры из tests/load/fixtures/."""
    global _DAG_FIXTURES
    fixtures_dir = Path(__file__).parent / "fixtures"
    if not fixtures_dir.exists():
        return
    for f in sorted(fixtures_dir.glob("dag_*.json")):
        try:
            with open(f, encoding="utf-8") as fh:
                _DAG_FIXTURES.append(json.load(fh))
                logger.debug("Загружена DAG-фикстура: %s", f.name)
        except Exception as exc:
            logger.warning("Ошибка загрузки %s: %s", f.name, exc)


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(title="Sphere Mock Server", version="2.0.0")


@app.on_event("startup")
async def _startup() -> None:
    _load_dag_fixtures()
    logger.info(
        "Mock Sphere Platform server запущен (v2.0, %d DAG-фикстур)",
        len(_DAG_FIXTURES),
    )


# ---------------------------------------------------------------------------
# REST: Регистрация устройств
# ---------------------------------------------------------------------------

@app.post("/api/v1/devices/register")
async def register_device(request: Request) -> JSONResponse:
    """Эмулирует регистрацию устройства."""
    body = await request.json()
    fingerprint = body.get("fingerprint", "")

    # Проверяем дубликат
    for did, info in _devices.items():
        if info.get("fingerprint") == fingerprint:
            return JSONResponse(
                status_code=409,
                content={"detail": "Device already registered", "device_id": did},
            )

    device_id = str(uuid.uuid4())
    jwt_token = f"mock_jwt_{device_id[:8]}"

    _devices[device_id] = {
        "device_id": device_id,
        "fingerprint": fingerprint,
        "name": body.get("name", ""),
        "type": body.get("type", "android"),
        "model": body.get("model", "unknown"),
        "os_version": body.get("os_version", ""),
        "agent_version": body.get("agent_version", ""),
        "status": "online",
        "registered_at": time.time(),
    }

    return JSONResponse(
        status_code=201,
        content={
            "device_id": device_id,
            "access_token": jwt_token,
            "jwt_token": jwt_token,  # обратная совместимость
            "status": "registered",
        },
    )


# ---------------------------------------------------------------------------
# REST: VPN
# ---------------------------------------------------------------------------

@app.post("/api/v1/vpn/assign")
async def vpn_assign(request: Request) -> JSONResponse:
    """VPN enrollment — назначает IP."""
    global _vpn_counter

    body = await request.json()
    device_id = body.get("device_id", "")

    if device_id in _vpn_assignments:
        return JSONResponse(
            status_code=200,
            content={
                "assigned_ip": _vpn_assignments[device_id],
                "status": "already_assigned",
            },
        )

    _vpn_counter += 1
    octet3 = (_vpn_counter >> 8) & 0xFF
    octet4 = _vpn_counter & 0xFF
    ip = f"10.100.{octet3}.{octet4}"
    _vpn_assignments[device_id] = ip

    return JSONResponse(
        status_code=201,
        content={"assigned_ip": ip, "status": "assigned"},
    )


@app.get("/api/v1/vpn/status")
async def vpn_status(device_id: str = "") -> JSONResponse:
    """Проверка статуса VPN."""
    if device_id in _vpn_assignments:
        return JSONResponse(
            content={
                "device_id": device_id,
                "vpn_active": True,
                "assigned_ip": _vpn_assignments[device_id],
            }
        )
    return JSONResponse(
        status_code=404,
        content={"detail": "VPN not assigned"},
    )


# ---------------------------------------------------------------------------
# REST: Устройства
# ---------------------------------------------------------------------------

@app.get("/api/v1/devices/{device_id}")
async def get_device(device_id: str) -> JSONResponse:
    """Информация об устройстве."""
    if device_id in _devices:
        return JSONResponse(content=_devices[device_id])
    return JSONResponse(status_code=404, content={"detail": "Not found"})


# ---------------------------------------------------------------------------
# REST: Health (расширенный)
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def health() -> JSONResponse:
    """Health check с расширенной статистикой."""
    return JSONResponse(content={
        "status": "ok",
        "devices_registered": len(_devices),
        "ws_connections": len(_ws_connections),
        "vpn_assignments": len(_vpn_assignments),
        "tasks_completed": len(_task_results),
        "tasks_in_progress": len(_task_progress),
        "dag_fixtures_loaded": len(_DAG_FIXTURES),
    })


# ---------------------------------------------------------------------------
# REST: Статистика задач (для проверки из тестов)
# ---------------------------------------------------------------------------

@app.get("/api/v1/tasks/stats")
async def task_stats() -> JSONResponse:
    """Статистика выполненных задач (для тестовой валидации)."""
    completed = sum(1 for r in _task_results.values() if r.get("status") == "completed")
    failed = sum(1 for r in _task_results.values() if r.get("status") == "failed")
    cancelled = sum(1 for r in _task_results.values() if r.get("status") == "cancelled")
    return JSONResponse(content={
        "total": len(_task_results),
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
        "acks_received": len(_command_acks),
    })


# ---------------------------------------------------------------------------
# WebSocket: /ws/android/{device_id}
# ---------------------------------------------------------------------------

@app.websocket("/ws/android/{device_id}")
async def ws_agent(ws: WebSocket, device_id: str) -> None:
    """WebSocket endpoint — имитирует серверную сторону Sphere Platform.

    Протокол полностью соответствует backend/api/ws/android/router.py:
    1. First-message auth (JWT / API-key)
    2. Noop как подтверждение auth
    3. Параллельные задачи: heartbeat_loop, noop_loop, task_sender
    4. Приём: pong, telemetry, task_progress, command_result, CommandAck
    """
    await ws.accept()

    # Шаг 1: First-message auth
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
        data = json.loads(raw)
        token = data.get("token", "")
        if not token:
            await ws.close(code=4001, reason="Missing token")
            return
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await ws.close(code=4002, reason="Auth timeout or bad JSON")
        return

    # Auth OK — отправляем noop как подтверждение
    await ws.send_text(json.dumps({"type": "noop", "message": "auth_ok"}))

    _ws_connections[device_id] = ws
    logger.debug("WS подключен: %s", device_id)

    try:
        # Запускаем параллельно: heartbeat + noop + task_sender + receiver
        heartbeat_task = asyncio.create_task(_heartbeat_loop(ws, device_id))
        noop_task = asyncio.create_task(_noop_loop(ws, device_id))
        task_sender = asyncio.create_task(_task_sender(ws, device_id))

        try:
            # Основной цикл приёма сообщений
            while True:
                raw_msg = await ws.receive_text()
                msg = json.loads(raw_msg)

                await _handle_agent_message(ws, device_id, msg)

        except WebSocketDisconnect:
            logger.debug("WS отключился: %s", device_id)
        except Exception as exc:
            logger.debug("WS ошибка [%s]: %s", device_id, exc)
        finally:
            heartbeat_task.cancel()
            noop_task.cancel()
            task_sender.cancel()
            for t in (heartbeat_task, noop_task, task_sender):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
    finally:
        _ws_connections.pop(device_id, None)


# ---------------------------------------------------------------------------
# Обработчик входящих сообщений от агента
# ---------------------------------------------------------------------------

async def _handle_agent_message(
    ws: WebSocket, device_id: str, msg: dict[str, Any]
) -> None:
    """Маршрутизация сообщений от агента (как в router.py)."""
    msg_type = msg.get("type", "")

    if msg_type == "pong":
        # Pong — OK (содержит ts + телеметрию: battery, cpu, ram_mb, etc.)
        pass

    elif msg_type == "telemetry":
        # Standalone телеметрия — кешируем
        if device_id in _devices:
            _devices[device_id].update({
                "battery": msg.get("battery"),
                "cpu": msg.get("cpu"),
                "ram_mb": msg.get("ram_mb"),
                "last_telemetry": time.time(),
            })

    elif msg_type == "task_progress":
        # Прогресс выполнения DAG — кешируем (аналог Redis task_progress:{task_id})
        task_id = msg.get("task_id", "")
        if task_id:
            _task_progress[task_id] = {
                "current_node": msg.get("current_node", ""),
                "nodes_done": msg.get("nodes_done", 0),
                "total_nodes": msg.get("total_nodes", 0),
                "updated_at": time.time(),
            }

    elif msg_type == "command_result":
        # Результат выполнения DAG
        command_id = msg.get("command_id", "")
        if command_id:
            _task_results[command_id] = {
                "status": msg.get("status", "unknown"),
                "result": msg.get("result", {}),
                "error": msg.get("error"),
                "received_at": time.time(),
                "device_id": device_id,
            }

    else:
        # CommandAck — нет поля "type", но есть command_id + status
        # (реальный формат APK: {"command_id":"uuid","status":"received"})
        command_id = msg.get("command_id", "")
        status = msg.get("status", "")
        if command_id and status:
            _command_acks[command_id] = status
            # Если это command_result (status = completed/failed/cancelled)
            if status in ("completed", "failed", "cancelled"):
                _task_results[command_id] = {
                    "status": status,
                    "result": msg.get("result", {}),
                    "error": msg.get("error"),
                    "received_at": time.time(),
                    "device_id": device_id,
                }


# ---------------------------------------------------------------------------
# Heartbeat loop (ping с ts — как в heartbeat.py)
# ---------------------------------------------------------------------------

async def _heartbeat_loop(ws: WebSocket, device_id: str) -> None:
    """Отправляем серверный ping каждые HEARTBEAT_INTERVAL секунд.

    Формат: {"type": "ping", "ts": time.time()}
    (Реальный бэкенд использует time.time(), не epoch_ms.)

    Первый ping приходит через 5s (как в реальном бэкенде — первый ping
    отправляется раньше, чтобы быстрее подтвердить связь), далее каждые 30s.
    """
    # Первый ping с укороченной задержкой
    await asyncio.sleep(5.0)
    try:
        await ws.send_text(json.dumps({
            "type": "ping",
            "ts": time.time(),
        }))
    except Exception:
        return

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            await ws.send_text(json.dumps({
                "type": "ping",
                "ts": time.time(),
            }))
        except Exception:
            break


# ---------------------------------------------------------------------------
# Noop keepalive (Cloudflare tunnel fix — как в router.py)
# ---------------------------------------------------------------------------

async def _noop_loop(ws: WebSocket, device_id: str) -> None:
    """Отправляем noop keepalive каждые NOOP_INTERVAL секунд.

    Формат: {"type": "noop"}
    Защита от таймаута Cloudflare Tunnel (100s idle timeout).
    """
    while True:
        await asyncio.sleep(NOOP_INTERVAL)
        try:
            await ws.send_text(json.dumps({"type": "noop"}))
        except Exception:
            break


# ---------------------------------------------------------------------------
# Task sender — отправка EXECUTE_DAG (реальный формат)
# ---------------------------------------------------------------------------

async def _task_sender(ws: WebSocket, device_id: str) -> None:
    """Периодически отправляем EXECUTE_DAG в реальном формате.

    Формат:
    {
      "command_id": "uuid",
      "type": "EXECUTE_DAG",
      "signed_at": epoch_float,
      "ttl_seconds": 3600,
      "payload": {
        "task_id": "uuid",
        "dag": { ...DAG из фикстуры... }
      }
    }
    """
    import random as _rnd

    await asyncio.sleep(TASK_SEND_DELAY)
    task_num = 0

    while True:
        await asyncio.sleep(_rnd.uniform(TASK_SEND_INTERVAL_MIN, TASK_SEND_INTERVAL_MAX))

        if _rnd.random() > TASK_SEND_PROBABILITY:
            continue

        task_num += 1
        command_id = str(uuid.uuid4())
        task_id = str(uuid.uuid4())

        # Выбираем DAG из загруженных фикстур (или генерируем минимальный)
        if _DAG_FIXTURES:
            dag = _rnd.choice(_DAG_FIXTURES)
        else:
            dag = _generate_minimal_dag()

        try:
            await ws.send_text(json.dumps({
                "command_id": command_id,
                "type": "EXECUTE_DAG",
                "signed_at": time.time(),
                "ttl_seconds": 3600,
                "payload": {
                    "task_id": task_id,
                    "dag": dag,
                },
            }))
        except Exception:
            break


def _generate_minimal_dag() -> dict[str, Any]:
    """Сгенерировать минимальный DAG (fallback если нет фикстур)."""
    return {
        "version": "1.0",
        "nodes": [
            {
                "id": "n1",
                "action": {"type": "get_device_info", "save_to": "info"},
                "next": "n2",
                "timeout_ms": 5000,
                "retry": 0,
            },
            {
                "id": "n2",
                "action": {"type": "sleep", "ms": 500},
                "next": "n3",
                "timeout_ms": 3000,
                "retry": 0,
            },
            {
                "id": "n3",
                "action": {"type": "screenshot", "save_to": "screen"},
                "next": None,
                "timeout_ms": 5000,
                "retry": 1,
            },
        ],
        "entry_node": "n1",
        "timeout_ms": 60000,
    }


# ---------------------------------------------------------------------------
# Запуск сервера (для standalone-режима)
# ---------------------------------------------------------------------------

def start_server(host: str = "127.0.0.1", port: int = 18080) -> None:
    """Запуск mock-сервера через uvicorn."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    start_server()
