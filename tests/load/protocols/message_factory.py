# -*- coding: utf-8 -*-
"""
Фабрика WebSocket/REST сообщений.

Генерирует JSON-сообщения, полностью совместимые с протоколом
Sphere Platform Android Agent ↔ Backend (v2 — реальный формат).

Форматы верифицированы по:
  • backend/api/ws/android/router.py — серверный обработчик
  • backend/websocket/heartbeat.py — heartbeat-менеджер
  • android/DagRunner.kt — клиентский обработчик
"""
from __future__ import annotations

import json
import random
import time
import uuid
from typing import Any


class MessageFactory:
    """Генерация протокольных сообщений для виртуального агента."""

    # ---------------------------------------------------------------
    # Исходящие: Агент → Сервер
    # ---------------------------------------------------------------

    @staticmethod
    def auth(token: str) -> str:
        """Первое сообщение аутентификации (first-message auth)."""
        return json.dumps({"token": token})

    @staticmethod
    def pong(
        *,
        ts: float | None = None,
        battery: int | None = None,
        cpu: float | None = None,
        ram_mb: int | None = None,
        screen_on: bool = True,
        vpn_active: bool = False,
        stream: bool = False,
    ) -> str:
        """Ответ на серверный ping (реальный формат APK).

        Pong содержит:
        - echo серверного `ts`
        - встроенную телеметрию (battery, cpu, ram_mb, screen_on, vpn_active, stream)

        Формат: {"type":"pong", "ts":<echo>, "battery":87, "cpu":45.2,
                 "ram_mb":2048, "screen_on":true, "vpn_active":true, "stream":false}
        """
        return json.dumps({
            "type": "pong",
            "ts": ts if ts is not None else time.time(),
            "battery": battery if battery is not None else random.randint(20, 95),
            "cpu": cpu if cpu is not None else round(random.uniform(5, 80), 1),
            "ram_mb": ram_mb if ram_mb is not None else random.randint(1024, 4096),
            "screen_on": screen_on,
            "vpn_active": vpn_active,
            "stream": stream,
        })

    @staticmethod
    def telemetry(
        *,
        battery: int | None = None,
        cpu: float | None = None,
        ram_mb: int | None = None,
        screen_on: bool = True,
        vpn_active: bool = False,
        stream: bool = False,
        uptime_sec: int = 0,
        wifi_rssi: int = -50,
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Standalone-телеметрия устройства (отдельно от pong)."""
        payload: dict[str, Any] = {
            "type": "telemetry",
            "battery": battery if battery is not None else random.randint(20, 95),
            "cpu": cpu if cpu is not None else round(random.uniform(5, 80), 1),
            "ram_mb": ram_mb if ram_mb is not None else random.randint(1024, 4096),
            "screen_on": screen_on,
            "vpn_active": vpn_active,
            "stream": stream,
            "uptime_sec": uptime_sec,
            "wifi_rssi": wifi_rssi,
        }
        if extra:
            payload.update(extra)
        return json.dumps(payload)

    @staticmethod
    def command_ack(command_id: str) -> str:
        """CommandAck — БЕЗ поля «type» (реальный формат APK!).

        Формат: {"command_id": "uuid", "status": "received"}
        """
        return json.dumps({
            "command_id": command_id,
            "status": "received",
        })

    @staticmethod
    def task_progress(
        task_id: str,
        current_node: str,
        nodes_done: int,
        total_nodes: int,
    ) -> str:
        """Прогресс выполнения DAG (после каждого узла).

        Формат: {"type":"task_progress", "task_id":"uuid",
                 "current_node":"n3", "nodes_done":3, "total_nodes":12}
        """
        return json.dumps({
            "type": "task_progress",
            "task_id": task_id,
            "current_node": current_node,
            "nodes_done": nodes_done,
            "total_nodes": total_nodes,
        })

    @staticmethod
    def command_result(
        command_id: str,
        status: str = "completed",
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> str:
        """Результат выполнения DAG (command_result).

        Формат: {"command_id":"uuid", "status":"completed/failed",
                 "result":{"nodes_executed":N, "success":bool,
                           "failed_node":str|null, "node_logs":[...]}}
        """
        payload: dict[str, Any] = {
            "command_id": command_id,
            "status": status,
        }
        if result is not None:
            payload["result"] = result
        if error is not None:
            payload["error"] = error
        return json.dumps(payload)

    # ---------------------------------------------------------------
    # Исходящие: Сервер → Агент (для mock-сервера)
    # ---------------------------------------------------------------

    @staticmethod
    def server_ping() -> str:
        """Серверный ping (реальный формат heartbeat.py).

        Формат: {"type": "ping", "ts": time.time()}
        """
        return json.dumps({"type": "ping", "ts": time.time()})

    @staticmethod
    def server_noop() -> str:
        """Серверный noop keepalive (Cloudflare tunnel fix).

        Формат: {"type": "noop"}
        """
        return json.dumps({"type": "noop"})

    @staticmethod
    def server_execute_dag(
        dag: dict[str, Any],
        command_id: str | None = None,
        task_id: str | None = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """Серверная команда EXECUTE_DAG (реальный формат).

        Формат:
        {
          "command_id": "uuid",
          "type": "EXECUTE_DAG",
          "signed_at": epoch_float,
          "ttl_seconds": 3600,
          "payload": {
            "task_id": "uuid",
            "dag": { ...DAG... }
          }
        }
        """
        cid = command_id or str(uuid.uuid4())
        tid = task_id or str(uuid.uuid4())
        return json.dumps({
            "command_id": cid,
            "type": "EXECUTE_DAG",
            "signed_at": time.time(),
            "ttl_seconds": ttl_seconds,
            "payload": {
                "task_id": tid,
                "dag": dag,
            },
        })

    @staticmethod
    def server_cancel_dag(command_id: str) -> str:
        """Серверная команда CANCEL_DAG."""
        return json.dumps({
            "command_id": command_id,
            "type": "CANCEL_DAG",
        })

    @staticmethod
    def server_pause_dag(command_id: str) -> str:
        """Серверная команда PAUSE_DAG."""
        return json.dumps({
            "command_id": command_id,
            "type": "PAUSE_DAG",
        })

    @staticmethod
    def server_resume_dag(command_id: str) -> str:
        """Серверная команда RESUME_DAG."""
        return json.dumps({
            "command_id": command_id,
            "type": "RESUME_DAG",
        })

    # ---------------------------------------------------------------
    # REST payloads
    # ---------------------------------------------------------------

    @staticmethod
    def device_register_payload(
        *,
        device_id: str,
        serial: str,
        model: str,
        android_version: str,
        fingerprint: str,
        app_version: str = "2.1.0",
    ) -> dict[str, Any]:
        """Тело POST /api/v1/devices/register."""
        return {
            "device_id": device_id,
            "serial": serial,
            "model": model,
            "android_version": android_version,
            "fingerprint": fingerprint,
            "app_version": app_version,
        }

    @staticmethod
    def vpn_assign_payload(device_id: str) -> dict[str, Any]:
        """Тело POST /api/v1/vpn/assign."""
        return {"device_id": device_id}
