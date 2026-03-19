# -*- coding: utf-8 -*-
"""
Виртуальный агент — ядро нагрузочного теста.

Каждый VirtualAgent — одна asyncio-корутина, полностью воспроизводящая
жизненный цикл реального Android-агента Sphere Platform:

    CREATED → REGISTERING → CONNECTING → ONLINE ⇄ EXECUTING → DEAD

Протокол воспроизводится 1-в-1 с реальным APK (DagRunner.kt + router.py):
  • First-message auth (JWT или API-key)
  • Pong: эхо серверного `ts` + встроенная телеметрия (battery, cpu, ram_mb,
    screen_on, vpn_active, stream)
  • Noop keepalive (обновляет watchdog-таймер)
  • CommandAck **без** поля `type` — `{command_id, status: "received"}`
  • EXECUTE_DAG → DagScriptEngine → per-node retry/timeout/progress → command_result
  • CANCEL_DAG / PAUSE_DAG / RESUME_DAG
  • task_progress после каждого узла DAG
  • command_result: `{command_id, status, result: {nodes_executed, success, failed_node, node_logs}}`
  • Pending results — сохранение/отправка при реконнекте
  • Бинарные фреймы (H.264 стриминг, если включено)
  • Случайные обрывы сети + exponential backoff с jitter
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from tests.load.core.dag_script_engine import DagScriptEngine, ProgressEvent

if TYPE_CHECKING:
    from tests.load.core.identity_factory import AgentIdentity
    from tests.load.core.metrics_collector import MetricsCollector

logger = logging.getLogger("loadtest.agent")


# ---------------------------------------------------------------------------
# Состояния агента
# ---------------------------------------------------------------------------

class AgentState(Enum):
    """Состояния конечного автомата виртуального агента."""

    CREATED = auto()
    REGISTERING = auto()
    CONNECTING = auto()
    ONLINE = auto()
    EXECUTING = auto()
    RECONNECTING = auto()
    DEAD = auto()


# ---------------------------------------------------------------------------
# Конфигурация поведения
# ---------------------------------------------------------------------------

class AgentBehavior:
    """Параметры поведения виртуального агента (конфигурируемо)."""

    def __init__(
        self,
        heartbeat_interval: float = 30.0,
        telemetry_interval: float = 10.0,
        watchdog_timeout: float = 90.0,
        reconnect_base: float = 1.0,
        reconnect_max: float = 30.0,
        reconnect_jitter: float = 0.2,
        max_reconnect_retries: int = 10,
        task_success_rate: float = 0.80,
        task_failure_rate: float = 0.15,
        task_duration_min: float = 2.0,
        task_duration_max: float = 30.0,
        random_disconnect_rate: float = 0.001,
        enable_vpn: bool = True,
        enable_video: bool = False,
        video_fps: int = 15,
        # --- Новые параметры для реалистичного DAG ---
        dag_speed_factor: float = 0.1,
        max_pending_results: int = 50,
    ) -> None:
        self.heartbeat_interval = heartbeat_interval
        self.telemetry_interval = telemetry_interval
        self.watchdog_timeout = watchdog_timeout
        self.reconnect_base = reconnect_base
        self.reconnect_max = reconnect_max
        self.reconnect_jitter = reconnect_jitter
        self.max_reconnect_retries = max_reconnect_retries
        self.task_success_rate = task_success_rate
        self.task_failure_rate = task_failure_rate
        self.task_duration_min = task_duration_min
        self.task_duration_max = task_duration_max
        self.random_disconnect_rate = random_disconnect_rate
        self.enable_vpn = enable_vpn
        self.enable_video = enable_video
        self.video_fps = video_fps
        self.dag_speed_factor = dag_speed_factor
        self.max_pending_results = max_pending_results


# ---------------------------------------------------------------------------
# VirtualAgent
# ---------------------------------------------------------------------------

class VirtualAgent:
    """Виртуальный агент — один экземпляр эмулируемого Android-устройства.

    Параметры:
        identity: Неизменяемая идентичность агента.
        behavior: Конфигурация поведения.
        metrics: Общий сборщик метрик.
        base_url: Базовый URL сервера (``http://host:port``).
        ws_url: WebSocket URL (``ws://host:port``).
    """

    def __init__(
        self,
        identity: AgentIdentity,
        behavior: AgentBehavior,
        metrics: MetricsCollector,
        base_url: str,
        ws_url: str,
    ) -> None:
        self.identity = identity
        self.behavior = behavior
        self.metrics = metrics
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url.rstrip("/")

        # Состояние
        self.state = AgentState.CREATED
        self._ws: Any | None = None
        self._session: Any | None = None  # aiohttp.ClientSession
        self._tasks: list[asyncio.Task[Any]] = []
        self._stop_event = asyncio.Event()
        self._heartbeat_seq: int = 0
        self._last_pong_ts: float = 0.0
        self._start_time: float = 0.0
        self._reconnect_count: int = 0

        # Данные регистрации
        self.registered_device_id: str | None = None
        self.jwt_token: str | None = None
        self.vpn_enrolled: bool = False
        self.vpn_ip: str | None = None
        self.executing_task: bool = False
        self._current_task_id: str | None = None

        # --- Реалистичный протокол ---
        # DagScriptEngine — движок выполнения DAG
        self._dag_engine: DagScriptEngine | None = None
        # Pending results (имитация EncryptedSharedPreferences)
        self._pending_results: list[dict[str, Any]] = []
        # Текущая streaming-сессия
        self._streaming: bool = False

    # ---------------------------------------------------------------
    # Публичный API
    # ---------------------------------------------------------------

    async def run(self) -> None:
        """Главный цикл жизни агента (одна корутина).

        Вызывается из AgentPool — представляет собой полный жизненный
        цикл: регистрация → подключение → online-loop → reconnect.
        """
        import aiohttp

        self._start_time = time.monotonic()
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
        )
        try:
            # Шаг 1: регистрация
            await self._register()

            # Шаг 2: основной цикл (connect → online → reconnect)
            while not self._stop_event.is_set():
                try:
                    await self._connect_and_serve()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug(
                        "[%s] Обрыв соединения: %s",
                        self.identity.serial,
                        exc,
                    )
                    self.metrics.inc("ws_disconnect_total")

                    if self._reconnect_count >= self.behavior.max_reconnect_retries:
                        self.state = AgentState.DEAD
                        self.metrics.inc("agent_dead_total")
                        logger.warning(
                            "[%s] Превышен лимит reconnect → DEAD",
                            self.identity.serial,
                        )
                        return

                    self.state = AgentState.RECONNECTING
                    delay = self._backoff_delay()
                    self._reconnect_count += 1
                    self.metrics.inc("ws_reconnect_total")
                    logger.debug(
                        "[%s] Reconnect #%d через %.1fs",
                        self.identity.serial,
                        self._reconnect_count,
                        delay,
                    )
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup()

    async def stop(self) -> None:
        """Остановить агента gracefully."""
        self._stop_event.set()
        for t in self._tasks:
            t.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    # ---------------------------------------------------------------
    # Регистрация устройства (REST)
    # ---------------------------------------------------------------

    async def _register(self) -> None:
        """POST /api/v1/devices/register — регистрация устройства.

        Формат совместим с реальным backend (DeviceRegisterRequest):
        fingerprint, name, device_type, android_version, model.
        Ответ: device_id, access_token (JWT), refresh_token.
        """
        self.state = AgentState.REGISTERING
        url = f"{self.base_url}/api/v1/devices/register"
        payload = {
            "fingerprint": self.identity.fingerprint,
            "name": f"load-{self.identity.serial}",
            "device_type": "ldplayer",
            "android_version": self.identity.android_version,
            "model": self.identity.model,
        }
        headers = {
            "X-API-Key": self.identity.api_key,
            "Content-Type": "application/json",
        }

        t0 = time.monotonic()
        try:
            assert self._session is not None
            async with self._session.post(
                url, json=payload, headers=headers
            ) as resp:
                elapsed_ms = (time.monotonic() - t0) * 1000
                self.metrics.record("registration_latency_ms", elapsed_ms)

                if resp.status in (200, 201):
                    data = await resp.json()
                    self.registered_device_id = data.get(
                        "device_id", self.identity.device_id
                    )
                    # Реальный backend возвращает access_token (JWT),
                    # mock-сервер — jwt_token. Поддерживаем оба.
                    self.jwt_token = (
                        data.get("access_token")
                        or data.get("jwt_token")
                    )
                    self.metrics.inc("registration_success")
                    logger.debug(
                        "[%s] Зарегистрирован: device_id=%s",
                        self.identity.serial,
                        self.registered_device_id,
                    )
                elif resp.status == 409:
                    # Устройство уже существует — нормально при повторных запусках
                    self.registered_device_id = self.identity.device_id
                    self.metrics.inc("registration_duplicate")
                    logger.debug(
                        "[%s] Уже зарегистрирован (409)",
                        self.identity.serial,
                    )
                else:
                    body = await resp.text()
                    self.metrics.inc("registration_error")
                    logger.warning(
                        "[%s] Ошибка регистрации %d: %s",
                        self.identity.serial,
                        resp.status,
                        body[:200],
                    )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            self.metrics.record("registration_latency_ms", elapsed_ms)
            self.metrics.inc("registration_error")
            logger.warning(
                "[%s] Ошибка регистрации: %s", self.identity.serial, exc
            )

    # ---------------------------------------------------------------
    # WebSocket: подключение + online-loop
    # ---------------------------------------------------------------

    async def _connect_and_serve(self) -> None:
        """Один полный цикл: connect → auth → online → (обрыв)."""
        from websockets.asyncio.client import connect

        self.state = AgentState.CONNECTING
        device_id = self.registered_device_id or self.identity.device_id
        ws_endpoint = f"{self.ws_url}/ws/android/{device_id}"

        t0 = time.monotonic()
        try:
            self._ws = await connect(
                ws_endpoint,
                additional_headers={},
                open_timeout=15,
                close_timeout=5,
                max_size=2**20,  # 1 МБ макс. размер фрейма
            )
        except Exception:
            elapsed = (time.monotonic() - t0) * 1000
            self.metrics.record("ws_connect_latency_ms", elapsed)
            self.metrics.inc("ws_connect_error")
            raise

        connect_elapsed = (time.monotonic() - t0) * 1000
        self.metrics.record("ws_connect_latency_ms", connect_elapsed)
        self.metrics.inc("ws_connect_success")

        try:
            # First-message auth: API-key (sphr_*) предпочтительнее JWT,
            # т.к. JWT истекает за 30 мин, а API-key бессрочный.
            auth_token = self.identity.api_key or self.jwt_token
            auth_msg = json.dumps({"token": auth_token})
            t_auth = time.monotonic()
            await self._ws.send(auth_msg)

            # Ожидаем ответ (auth_ack или другой)
            await asyncio.wait_for(self._ws.recv(), timeout=10)
            auth_elapsed = (time.monotonic() - t_auth) * 1000
            self.metrics.record("ws_auth_latency_ms", auth_elapsed)

            # Успешное подключение
            self.state = AgentState.ONLINE
            self._reconnect_count = 0
            self._last_pong_ts = time.monotonic()
            self.metrics.inc("ws_online_total")
            self.metrics.set_gauge(
                "ws_active_connections",
                self.metrics.gauge("ws_active_connections") + 1,
            )

            # VPN enrollment (если включено)
            if self.behavior.enable_vpn and not self.vpn_enrolled:
                await self._vpn_enroll()

            # Flush pending results после реконнекта (как в реальном APK)
            await self._flush_pending_results()

            # Запуск параллельных задач: heartbeat, telemetry, receiver
            self._tasks = [
                asyncio.create_task(self._heartbeat_loop()),
                asyncio.create_task(self._telemetry_loop()),
                asyncio.create_task(self._receiver_loop()),
            ]
            if self.behavior.enable_vpn:
                self._tasks.append(
                    asyncio.create_task(self._vpn_status_loop())
                )

            # Ожидаем завершения (одна из задач упадёт → reconnect)
            done, pending = await asyncio.wait(
                self._tasks, return_when=asyncio.FIRST_EXCEPTION
            )
            for t in pending:
                t.cancel()
            # Поднимаем исключение из упавшей задачи
            for t in done:
                if t.exception() is not None:
                    raise t.exception()  # type: ignore[misc]

        finally:
            self.metrics.set_gauge(
                "ws_active_connections",
                max(0, self.metrics.gauge("ws_active_connections") - 1),
            )
            if self._ws is not None:
                try:
                    await self._ws.close()
                except Exception:
                    pass
            self._ws = None
            self.state = AgentState.RECONNECTING

    # ---------------------------------------------------------------
    # Heartbeat (pong на серверный ping)
    # ---------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Ожидаем серверные ping и отвечаем pong.

        Также проверяем watchdog — если давно не было ping от сервера,
        закрываем соединение для reconnect.
        """
        while not self._stop_event.is_set():
            # Проверяем watchdog
            if (
                time.monotonic() - self._last_pong_ts
                > self.behavior.watchdog_timeout
            ):
                logger.debug(
                    "[%s] Watchdog timeout (%.0fs без ping)",
                    self.identity.serial,
                    self.behavior.watchdog_timeout,
                )
                self.metrics.inc("ws_watchdog_timeout")
                raise ConnectionError("Watchdog timeout — нет ping от сервера")

            await asyncio.sleep(self.behavior.heartbeat_interval)

    # ---------------------------------------------------------------
    # Telemetry (device status)
    # ---------------------------------------------------------------

    async def _telemetry_loop(self) -> None:
        """Отправка telemetry каждые N секунд.

        Это standalone-телеметрия (отдельно от pong).
        В pong тоже идут поля battery/cpu/ram, но бэкенд обрабатывает
        оба источника — telemetry кешируется в status_cache.
        """
        while not self._stop_event.is_set():
            jitter = random.uniform(-1.0, 1.0)
            await asyncio.sleep(self.behavior.telemetry_interval + jitter)

            if self._ws is None:
                break

            elapsed = time.monotonic() - self._start_time
            msg = {
                "type": "telemetry",
                "battery": max(15, 100 - int(elapsed / 60)),
                "cpu": round(max(0, min(100, random.gauss(30, 15))), 1),
                "ram_mb": random.randint(
                    self.identity.memory_mb // 3,
                    self.identity.memory_mb * 2 // 3,
                ),
                "screen_on": True,
                "vpn_active": self.vpn_enrolled,
                "stream": self._streaming,
                "uptime_sec": int(elapsed),
                "wifi_rssi": random.randint(-80, -30),
            }

            try:
                t0 = time.monotonic()
                await self._ws.send(json.dumps(msg))
                elapsed_ms = (time.monotonic() - t0) * 1000
                self.metrics.record("ws_telemetry_send_ms", elapsed_ms)
                self.metrics.inc("telemetry_sent")
            except Exception:
                break

            # Случайный disconnect (имитация нестабильной сети)
            if random.random() < self.behavior.random_disconnect_rate:
                self.metrics.inc("random_disconnect")
                raise ConnectionError("Имитация случайного обрыва сети")

    # ---------------------------------------------------------------
    # Receiver — приём сообщений от сервера
    # ---------------------------------------------------------------

    async def _receiver_loop(self) -> None:
        """Приём и обработка сообщений от сервера."""
        while not self._stop_event.is_set():
            if self._ws is None:
                break
            try:
                raw = await self._ws.recv()
            except Exception:
                break

            if isinstance(raw, bytes):
                # Binary frame (video backpressure или другое) — игнорируем
                self.metrics.inc("ws_binary_received")
                continue

            self.metrics.inc("ws_messages_received")

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")
            await self._handle_message(msg_type, data)

    async def _handle_message(self, msg_type: str, data: dict[str, Any]) -> None:
        """Маршрутизация входящих сообщений (1-в-1 с router.py)."""
        if msg_type == "ping":
            await self._handle_ping(data)
        elif msg_type == "noop":
            # Keepalive (Cloudflare tunnel fix) — обновляем watchdog
            self._last_pong_ts = time.monotonic()
        elif msg_type == "EXECUTE_DAG":
            await self._handle_execute_dag(data)
        elif msg_type == "task_command":
            # Обратная совместимость со старым форматом
            await self._handle_execute_dag(data)
        elif msg_type == "CANCEL_DAG":
            await self._handle_cancel_dag(data)
        elif msg_type == "PAUSE_DAG":
            if self._dag_engine is not None:
                self._dag_engine.pause()
                self.metrics.inc("dag_pause_received")
        elif msg_type == "RESUME_DAG":
            if self._dag_engine is not None:
                self._dag_engine.resume()
                self.metrics.inc("dag_resume_received")
        elif msg_type in ("SHELL", "UPLOAD_LOGCAT"):
            await self._handle_generic_command(data)
        elif msg_type in ("start_stream", "stop_stream"):
            self._streaming = msg_type == "start_stream"
            self.metrics.inc(f"cmd_{msg_type}")
        else:
            self.metrics.inc("ws_unknown_message_type")
            self._last_pong_ts = time.monotonic()

    # ---------------------------------------------------------------
    # Обработчик: Ping → Pong
    # ---------------------------------------------------------------

    async def _handle_ping(self, data: dict[str, Any]) -> None:
        """Ответить pong на серверный ping.

        Реальный протокол (heartbeat.py + router.py):
        - Сервер: {"type": "ping", "ts": time.time()}
        - Агент:  {"type": "pong", "ts": <echo>, "battery": 87, "cpu": 45.2,
                   "ram_mb": 2048, "screen_on": true, "vpn_active": true, "stream": false}
        """
        server_ts = data.get("ts", time.time())
        elapsed = time.monotonic() - self._start_time

        pong_msg = json.dumps({
            "type": "pong",
            "ts": server_ts,
            "battery": max(15, 100 - int(elapsed / 60)),
            "cpu": round(max(0, min(100, random.gauss(30, 15))), 1),
            "ram_mb": random.randint(
                self.identity.memory_mb // 3,
                self.identity.memory_mb * 2 // 3,
            ),
            "screen_on": True,
            "vpn_active": self.vpn_enrolled,
            "stream": self._streaming,
        })

        t0 = time.monotonic()
        if self._ws is not None:
            await self._ws.send(pong_msg)
        elapsed_ms = (time.monotonic() - t0) * 1000

        self.metrics.record("ws_heartbeat_rtt_ms", elapsed_ms)
        self.metrics.inc("heartbeat_pong_sent")
        self._last_pong_ts = time.monotonic()

    # ---------------------------------------------------------------
    # Обработчик: Task Command (выполнение DAG-скрипта)
    # ---------------------------------------------------------------

    async def _handle_execute_dag(self, data: dict[str, Any]) -> None:
        """Выполнение DAG-скрипта — точная имитация DagRunner.kt.

        Протокол:
        1. Входящее: {"command_id":"uuid", "type":"EXECUTE_DAG",
                      "payload":{"task_id":"uuid", "dag":{...}}}
           Или legacy: {"type":"task_command", "task_id":"...", "dag":{...}}
        2. Отправляем CommandAck (БЕЗ поля "type"!):
           {"command_id":"uuid", "status":"received"}
        3. Выполняем DAG через DagScriptEngine:
           - Per-node retry с exponential backoff
           - task_progress после каждого узла
        4. Отправляем command_result:
           {"command_id":"uuid", "status":"completed/failed",
            "result":{"nodes_executed":N, "success":bool,
                      "failed_node":str|null, "node_logs":[...]}}
        5. Если WS отключён — сохраняем в pending_results
        """
        # Извлекаем идентификаторы (поддержка обоих форматов)
        command_id = data.get("command_id", "")
        payload = data.get("payload", {})
        task_id = payload.get("task_id") or data.get("task_id") or command_id or str(uuid.uuid4())
        dag = payload.get("dag") or data.get("dag", {})

        if not command_id:
            command_id = task_id

        self._current_task_id = task_id
        self.executing_task = True
        self.state = AgentState.EXECUTING
        self.metrics.inc("task_received")

        try:
            # 1. CommandAck — БЕЗ поля "type" (как в реальном APK!)
            ack_msg = json.dumps({
                "command_id": command_id,
                "status": "received",
            })
            if self._ws is not None:
                await self._ws.send(ack_msg)
            self.metrics.inc("task_ack_sent")

            # 2. Создаём DagScriptEngine с callback для прогресса
            async def send_progress(event: ProgressEvent) -> None:
                """Отправить task_progress серверу после каждого узла."""
                progress_msg = json.dumps({
                    "type": "task_progress",
                    "task_id": event.task_id,
                    "current_node": event.current_node,
                    "nodes_done": event.nodes_done,
                    "total_nodes": event.total_nodes,
                })
                if self._ws is not None:
                    try:
                        await self._ws.send(progress_msg)
                        self.metrics.inc("task_progress_sent")
                    except Exception:
                        pass  # WS может отключиться во время выполнения

            self._dag_engine = DagScriptEngine(
                success_rate=self.behavior.task_success_rate,
                speed_factor=self.behavior.dag_speed_factor,
                on_progress=send_progress,
            )

            # 3. Выполнение DAG
            t0 = time.monotonic()
            dag_result = await self._dag_engine.execute(dag, task_id)
            duration_ms = (time.monotonic() - t0) * 1000

            # 4. Формируем command_result (формат router.py)
            status = "completed" if dag_result.success else "failed"
            if dag_result.cancelled:
                status = "cancelled"

            result_payload: dict[str, Any] = {
                "command_id": command_id,
                "status": status,
                "result": dag_result.to_dict(),
            }
            if dag_result.error:
                result_payload["error"] = dag_result.error

            # 5. Отправляем или сохраняем в pending
            if self._ws is not None:
                try:
                    await self._ws.send(json.dumps(result_payload))
                    self.metrics.inc("command_result_sent")
                except Exception:
                    self._save_pending_result(result_payload)
            else:
                self._save_pending_result(result_payload)

            self.metrics.inc(f"task_{status}")
            self.metrics.record("task_execution_ms", duration_ms)

        finally:
            self._dag_engine = None
            self.executing_task = False
            self._current_task_id = None
            self.state = AgentState.ONLINE

    # ---------------------------------------------------------------
    # Обработчик: CANCEL_DAG
    # ---------------------------------------------------------------

    async def _handle_cancel_dag(self, data: dict[str, Any]) -> None:
        """Обработка CANCEL_DAG — прерывание текущего DAG."""
        command_id = data.get("command_id", "")
        if self._dag_engine is not None:
            self._dag_engine.cancel()
            self.metrics.inc("dag_cancel_received")
            logger.debug(
                "[%s] CANCEL_DAG для command_id=%s",
                self.identity.serial,
                command_id,
            )
        else:
            # DAG не выполняется — отправляем ack что ничего не отменено
            if self._ws is not None:
                try:
                    await self._ws.send(json.dumps({
                        "command_id": command_id,
                        "status": "no_active_dag",
                    }))
                except Exception:
                    pass

    # ---------------------------------------------------------------
    # Pending results (имитация EncryptedSharedPreferences)
    # ---------------------------------------------------------------

    def _save_pending_result(self, result: dict[str, Any]) -> None:
        """Сохранить результат в pending (WS офлайн)."""
        if len(self._pending_results) >= self.behavior.max_pending_results:
            # Лимит — удаляем самый старый (как в DagRunner.kt)
            self._pending_results.pop(0)
            self.metrics.inc("pending_results_dropped")

        self._pending_results.append({
            **result,
            "saved_at": time.time(),
        })
        self.metrics.inc("pending_results_saved")

    async def _flush_pending_results(self) -> None:
        """Отправить накопленные pending results после реконнекта."""
        if not self._pending_results or self._ws is None:
            return

        flushed = 0
        while self._pending_results:
            result = self._pending_results.pop(0)
            try:
                await self._ws.send(json.dumps(result))
                flushed += 1
            except Exception:
                # Не удалось — кладём обратно
                self._pending_results.insert(0, result)
                break

        if flushed > 0:
            self.metrics.inc("pending_results_flushed", flushed)
            logger.debug(
                "[%s] Отправлено %d pending results",
                self.identity.serial,
                flushed,
            )

    # ---------------------------------------------------------------
    # Обработчик: Generic command (SHELL, UPLOAD_LOGCAT)
    # ---------------------------------------------------------------

    async def _handle_generic_command(self, data: dict[str, Any]) -> None:
        """Имитация выполнения произвольной команды."""
        cmd_id = data.get("command_id", str(uuid.uuid4()))
        cmd_type = data.get("type", "unknown")
        self.metrics.inc(f"cmd_{cmd_type}")

        # Имитация задержки выполнения
        await asyncio.sleep(random.uniform(0.1, 0.5))

        result_msg = json.dumps({
            "type": "command_result",
            "command_id": cmd_id,
            "status": "completed",
            "result": {"output": f"Synthetic {cmd_type} OK"},
        })
        if self._ws is not None:
            await self._ws.send(result_msg)
        self.metrics.inc("command_result_sent")

    # ---------------------------------------------------------------
    # VPN enrollment
    # ---------------------------------------------------------------

    async def _vpn_enroll(self) -> None:
        """POST /api/v1/vpn/assign — VPN enrollment."""
        url = f"{self.base_url}/api/v1/vpn/assign"
        device_id = self.registered_device_id or self.identity.device_id
        payload = {
            "device_id": device_id,
            "split_tunnel": True,
        }
        headers = {
            "Authorization": f"Bearer {self.jwt_token}" if self.jwt_token else "",
            "X-API-Key": self.identity.api_key,
            "Content-Type": "application/json",
        }

        t0 = time.monotonic()
        try:
            assert self._session is not None
            async with self._session.post(
                url, json=payload, headers=headers
            ) as resp:
                elapsed_ms = (time.monotonic() - t0) * 1000
                self.metrics.record("vpn_enroll_latency_ms", elapsed_ms)

                if resp.status in (200, 201):
                    data = await resp.json()
                    self.vpn_enrolled = True
                    self.vpn_ip = data.get("assigned_ip", "10.100.0.?")
                    self.metrics.inc("vpn_enroll_success")
                else:
                    self.metrics.inc("vpn_enroll_error")
        except Exception:
            self.metrics.inc("vpn_enroll_error")

    async def _vpn_status_loop(self) -> None:
        """Периодическая проверка статуса VPN."""
        while not self._stop_event.is_set():
            await asyncio.sleep(60 + random.uniform(-5, 5))

            if not self.vpn_enrolled:
                continue

            device_id = self.registered_device_id or self.identity.device_id
            url = f"{self.base_url}/api/v1/vpn/status?device_id={device_id}"
            headers = {
                "Authorization": (
                    f"Bearer {self.jwt_token}" if self.jwt_token else ""
                ),
                "X-API-Key": self.identity.api_key,
            }

            try:
                assert self._session is not None
                t0 = time.monotonic()
                async with self._session.get(url, headers=headers) as _resp:
                    elapsed_ms = (time.monotonic() - t0) * 1000
                    self.metrics.record("vpn_status_latency_ms", elapsed_ms)
                    self.metrics.inc("vpn_status_check")
            except Exception:
                self.metrics.inc("vpn_status_error")

    # ---------------------------------------------------------------
    # Утилиты
    # ---------------------------------------------------------------

    def _backoff_delay(self) -> float:
        """Рассчитать задержку reconnect c exponential backoff + jitter."""
        base = min(
            self.behavior.reconnect_base * (2 ** self._reconnect_count),
            self.behavior.reconnect_max,
        )
        jitter = base * random.uniform(
            -self.behavior.reconnect_jitter,
            self.behavior.reconnect_jitter,
        )
        return max(0.1, base + jitter)

    async def _cleanup(self) -> None:
        """Освобождение ресурсов."""
        for t in self._tasks:
            t.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session is not None:
            try:
                await self._session.close()
            except Exception:
                pass
        self._ws = None
        self._session = None
