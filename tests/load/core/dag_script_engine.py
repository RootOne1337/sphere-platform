# -*- coding: utf-8 -*-
"""
DagScriptEngine — синтетический движок выполнения DAG-скриптов.

Точно воспроизводит логику реального DagRunner.kt из Android-агента:
  • Обход графа от entry_node по цепочке next / on_true / on_false
  • Per-node retry с exponential backoff (50ms × 2^n, max 5s)
  • Per-node timeout (default 30s), global timeout (default 30min)
  • Формирование node_logs в формате бэкенда
  • task_progress после каждого узла
  • CANCEL / PAUSE / RESUME
  • Имитация длительности действий по типу (tap ~45ms, find ~200ms, и т.д.)

Для нагрузочного теста узлы не выполняются реально, а имитируются
с реалистичными задержками и вероятностями ошибок.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("loadtest.dag_engine")

# ---------------------------------------------------------------------------
# Константы (совпадают с DagRunner.kt)
# ---------------------------------------------------------------------------

MAX_DAG_NODES = 500
MAX_EXECUTE_DEPTH = 10
MAX_PENDING_RESULTS = 50

# Exponential backoff: 50ms × 2^attempt, max 5000ms
_RETRY_BASE_MS = 50
_RETRY_MAX_MS = 5000

# Реалистичные длительности действий (мс) — из профилирования APK
_ACTION_TIMING: dict[str, tuple[float, float]] = {
    "tap":                  (30, 80),
    "swipe":                (200, 500),
    "long_press":           (600, 1200),
    "double_tap":           (80, 200),
    "type_text":            (150, 600),
    "key_event":            (20, 50),
    "sleep":                (0, 0),        # реальная задержка из action["ms"]
    "screenshot":           (300, 800),
    "find_element":         (100, 2000),
    "find_first_element":   (150, 3000),
    "tap_element":          (150, 1500),
    "tap_first_visible":    (200, 2500),
    "get_element_text":     (100, 800),
    "wait_for_element_gone":(500, 5000),
    "scroll":               (200, 500),
    "scroll_to":            (500, 8000),
    "launch_app":           (1500, 4000),
    "stop_app":             (200, 600),
    "open_url":             (500, 2000),
    "clear_app_data":       (300, 1000),
    "get_device_info":      (50, 200),
    "shell":                (50, 500),
    "input_clear":          (50, 200),
    "set_variable":         (1, 5),
    "get_variable":         (1, 5),
    "increment_variable":   (1, 5),
    "condition":            (50, 500),
    "assert":               (50, 500),
    "http_request":         (200, 5000),
    "lua":                  (10, 200),
    "loop":                 (0, 0),        # длительность определяется телом цикла
    "start":                (1, 3),
    "end":                  (1, 3),
}

# Вероятность ошибки для разных типов действий
_ACTION_ERROR_RATE: dict[str, float] = {
    "find_element":         0.05,
    "find_first_element":   0.04,
    "tap_element":          0.03,
    "tap_first_visible":    0.03,
    "wait_for_element_gone":0.02,
    "scroll_to":            0.04,
    "http_request":         0.03,
    "assert":               0.02,
    "condition":            0.01,
    "launch_app":           0.01,
}


# ---------------------------------------------------------------------------
# Результаты
# ---------------------------------------------------------------------------

@dataclass
class NodeLog:
    """Лог выполнения одного узла (формат бэкенда)."""
    node_id: str
    action_type: str
    duration_ms: int
    success: bool
    error: str | None = None
    output: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "node_id": self.node_id,
            "action_type": self.action_type,
            "duration_ms": self.duration_ms,
            "success": self.success,
        }
        if self.error is not None:
            d["error"] = self.error
        if self.output is not None:
            d["output"] = str(self.output)
        return d


@dataclass
class DagResult:
    """Результат выполнения DAG (формат command_result)."""
    nodes_executed: int = 0
    success: bool = True
    failed_node: str | None = None
    node_logs: list[NodeLog] = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes_executed": self.nodes_executed,
            "success": self.success,
            "failed_node": self.failed_node,
            "node_logs": [n.to_dict() for n in self.node_logs],
        }


# ---------------------------------------------------------------------------
# Callback для отправки прогресса
# ---------------------------------------------------------------------------

@dataclass
class ProgressEvent:
    """Событие прогресса — отправляется серверу после каждого узла."""
    task_id: str
    current_node: str
    nodes_done: int
    total_nodes: int


# ---------------------------------------------------------------------------
# DagScriptEngine
# ---------------------------------------------------------------------------

class DagScriptEngine:
    """Синтетический движок выполнения DAG-скриптов.

    Точно воспроизводит логику DagRunner.kt:
      - Обход графа по entry_node → next → ...
      - condition: on_true / on_false
      - Per-node retry с exponential backoff
      - Per-node timeout, global timeout
      - Формирование node_logs

    Параметры:
        success_rate: Общая вероятность успешного выполнения DAG (0.0–1.0).
        speed_factor: Множитель скорости (1.0 = реальное время,
                      0.1 = в 10 раз быстрее для нагрузочного теста).
        on_progress: Опциональный callback для отправки прогресса.
    """

    def __init__(
        self,
        success_rate: float = 0.85,
        speed_factor: float = 0.1,
        on_progress: Any | None = None,
    ) -> None:
        self._success_rate = success_rate
        self._speed_factor = speed_factor
        self._on_progress = on_progress

        # Управление: cancel / pause / resume
        self._cancel_requested = False
        self._paused = asyncio.Event()
        self._paused.set()  # Изначально НЕ приостановлено

        # Контекст (переменные DAG)
        self._ctx: dict[str, Any] = {}

    # ---------------------------------------------------------------
    # Управление
    # ---------------------------------------------------------------

    def cancel(self) -> None:
        """Запросить отмену текущего DAG (аналог CANCEL_DAG)."""
        self._cancel_requested = True
        # Если приостановлено — разблокировать, чтобы cancel сработал
        self._paused.set()

    def pause(self) -> None:
        """Приостановить выполнение (аналог PAUSE_DAG)."""
        self._paused.clear()

    def resume(self) -> None:
        """Возобновить выполнение (аналог RESUME_DAG)."""
        self._paused.set()

    # ---------------------------------------------------------------
    # Основной метод выполнения
    # ---------------------------------------------------------------

    async def execute(
        self,
        dag: dict[str, Any],
        task_id: str,
    ) -> DagResult:
        """Выполнить DAG и вернуть результат.

        Параметры:
            dag: DAG-граф (version, nodes, entry_node, timeout_ms).
            task_id: Идентификатор задачи.

        Возвращает:
            DagResult с node_logs и общим результатом.
        """
        self._cancel_requested = False
        self._paused.set()
        self._ctx = {}

        nodes = dag.get("nodes", [])
        entry = dag.get("entry_node", "n1")
        global_timeout_ms = dag.get("timeout_ms", 1_800_000)  # 30 минут

        if not nodes:
            return DagResult(success=False, error="DAG пуст: nodes=[]")

        if len(nodes) > MAX_DAG_NODES:
            return DagResult(
                success=False,
                error=f"DAG превышает лимит: {len(nodes)} > {MAX_DAG_NODES}",
            )

        # Построить index: id → node
        node_map: dict[str, dict[str, Any]] = {}
        for n in nodes:
            nid = n.get("id", "")
            if nid:
                node_map[nid] = n

        if entry not in node_map:
            return DagResult(
                success=False,
                error=f"entry_node '{entry}' не найден в nodes",
            )

        # Определяем, будет ли этот DAG успешным (pre-roll)
        dag_will_succeed = random.random() < self._success_rate
        # Если fail — выбираем случайный узел для ошибки
        # Используем низкий индекс чтобы гарантировать попадание
        # даже при коротком маршруте (condition → on_false → end)
        fail_at_node_idx = -1
        if not dag_will_succeed:
            fail_at_node_idx = random.randint(1, max(1, min(3, len(nodes) - 1)))

        result = DagResult()
        global_start = time.monotonic()

        current_id: str | None = entry
        node_counter = 0

        try:
            while current_id is not None:
                # Проверка cancel
                if self._cancel_requested:
                    result.cancelled = True
                    result.success = False
                    result.error = "Отменено по CANCEL_DAG"
                    break

                # Проверка pause
                await self._paused.wait()

                # Проверка global timeout
                elapsed_ms = (time.monotonic() - global_start) * 1000
                if elapsed_ms > global_timeout_ms * self._speed_factor:
                    result.success = False
                    result.error = f"Global timeout: {elapsed_ms:.0f}ms > {global_timeout_ms}ms"
                    break

                node = node_map.get(current_id)
                if node is None:
                    result.success = False
                    result.error = f"Узел '{current_id}' не найден"
                    break

                node_counter += 1
                action = node.get("action", {})
                action_type = action.get("type", "unknown")
                node_timeout_ms = node.get("timeout_ms", 30_000)
                max_retries = node.get("retry", 0)

                # Определяем, упадёт ли этот узел
                should_fail = (
                    not dag_will_succeed
                    and node_counter == fail_at_node_idx
                )

                # Выполнение с retry
                node_log = await self._execute_node_with_retry(
                    node_id=current_id,
                    action=action,
                    action_type=action_type,
                    node_timeout_ms=node_timeout_ms,
                    max_retries=max_retries,
                    force_fail=should_fail,
                )
                result.node_logs.append(node_log)
                result.nodes_executed = node_counter

                # Отправка прогресса
                if self._on_progress is not None:
                    event = ProgressEvent(
                        task_id=task_id,
                        current_node=current_id,
                        nodes_done=node_counter,
                        total_nodes=len(nodes),
                    )
                    await self._on_progress(event)

                # Обработка результата
                if not node_log.success:
                    result.success = False
                    result.failed_node = current_id
                    result.error = node_log.error
                    break

                # Маршрутизация: condition → on_true/on_false, иначе → next
                if action_type == "condition":
                    # Имитация: condition считается true с вероятностью 0.7
                    condition_result = random.random() < 0.7
                    if condition_result:
                        current_id = node.get("on_true")
                    else:
                        current_id = node.get("on_false")
                else:
                    current_id = node.get("next")

        except asyncio.CancelledError:
            result.success = False
            result.cancelled = True
            result.error = "Задача отменена (CancelledError)"
        except Exception as exc:
            result.success = False
            result.error = f"Непредвиденная ошибка: {exc}"

        return result

    # ---------------------------------------------------------------
    # Выполнение одного узла с retry
    # ---------------------------------------------------------------

    async def _execute_node_with_retry(
        self,
        node_id: str,
        action: dict[str, Any],
        action_type: str,
        node_timeout_ms: int,
        max_retries: int,
        force_fail: bool = False,
    ) -> NodeLog:
        """Выполнить узел с retry и exponential backoff.

        Логика полностью повторяет DagRunner.kt:
        - backoff = min(RETRY_BASE_MS × 2^attempt, RETRY_MAX_MS) + jitter
        - Per-node timeout обрамляет каждую попытку
        """
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            t0 = time.monotonic()
            try:
                # Timeout на одну попытку
                # Минимум 0.5s для asyncio overhead (Windows IOCP)
                scaled_timeout = (node_timeout_ms / 1000) * self._speed_factor
                # force_fail активен на всех попытках (а не только на последней),
                # чтобы гарантировать fail при success_rate=0.0
                result = await asyncio.wait_for(
                    self._execute_single_node(
                        node_id, action, action_type, force_fail,
                    ),
                    timeout=max(0.5, scaled_timeout),
                )
                duration_ms = int((time.monotonic() - t0) * 1000)
                return NodeLog(
                    node_id=node_id,
                    action_type=action_type,
                    duration_ms=duration_ms,
                    success=True,
                    output=result,
                )
            except asyncio.TimeoutError:
                duration_ms = int((time.monotonic() - t0) * 1000)
                last_error = f"Timeout {node_timeout_ms}ms на узле '{node_id}'"
            except _NodeExecutionError as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                last_error = str(exc)
            except Exception as exc:
                duration_ms = int((time.monotonic() - t0) * 1000)
                last_error = f"{type(exc).__name__}: {exc}"

            # Если есть ещё попытки — backoff
            if attempt < max_retries:
                backoff_ms = min(
                    _RETRY_BASE_MS * (2 ** attempt),
                    _RETRY_MAX_MS,
                )
                jitter = random.uniform(0, backoff_ms * 0.3)
                delay_sec = ((backoff_ms + jitter) / 1000) * self._speed_factor
                logger.debug(
                    "[DAG][%s] Retry %d/%d через %.0fms",
                    node_id, attempt + 1, max_retries, backoff_ms + jitter,
                )
                await asyncio.sleep(delay_sec)

        # Все попытки исчерпаны
        return NodeLog(
            node_id=node_id,
            action_type=action_type,
            duration_ms=int((time.monotonic() - t0) * 1000),
            success=False,
            error=last_error,
        )

    # ---------------------------------------------------------------
    # Имитация выполнения одного узла
    # ---------------------------------------------------------------

    async def _execute_single_node(
        self,
        node_id: str,
        action: dict[str, Any],
        action_type: str,
        force_fail: bool,
    ) -> Any:
        """Имитировать выполнение одного узла DAG.

        Длительность определяется по типу действия (из _ACTION_TIMING).
        Ошибки генерируются случайно (из _ACTION_ERROR_RATE) или
        принудительно через force_fail.
        """
        # Случайная ошибка на основе типа действия
        error_rate = _ACTION_ERROR_RATE.get(action_type, 0.0)
        if force_fail or (error_rate > 0 and random.random() < error_rate):
            # Генерируем реалистичное сообщение об ошибке
            err = self._generate_error_message(action_type, action)
            # Задержка до ошибки (частичное выполнение)
            timing = _ACTION_TIMING.get(action_type, (10, 100))
            if timing[1] > 0:
                wait = random.uniform(timing[0], timing[1]) / 1000 * self._speed_factor
                await asyncio.sleep(wait)
            raise _NodeExecutionError(err)

        # Успешное выполнение — имитация задержки
        if action_type == "sleep":
            sleep_ms = action.get("ms", 1000)
            await asyncio.sleep((sleep_ms / 1000) * self._speed_factor)
            return None

        if action_type == "loop":
            count = action.get("count", 3)
            body = action.get("body", [])
            for iteration in range(count):
                for body_node in body:
                    b_action = body_node.get("action", {})
                    b_type = b_action.get("type", "sleep")
                    timing = _ACTION_TIMING.get(b_type, (10, 100))
                    if timing[1] > 0:
                        wait = random.uniform(timing[0], timing[1]) / 1000 * self._speed_factor
                        await asyncio.sleep(wait)
            return {"iterations": count, "body_nodes": len(body)}

        # Стандартная задержка по типу
        timing = _ACTION_TIMING.get(action_type, (10, 100))
        if timing[1] > 0:
            wait = random.uniform(timing[0], timing[1]) / 1000 * self._speed_factor
            await asyncio.sleep(wait)

        # Генерируем реалистичный output
        return self._generate_output(action_type, action)

    # ---------------------------------------------------------------
    # Генерация реалистичных данных
    # ---------------------------------------------------------------

    @staticmethod
    def _generate_output(action_type: str, action: dict[str, Any]) -> Any:
        """Генерация реалистичного output для узла."""
        if action_type == "tap":
            x = action.get("x", random.randint(50, 1000))
            y = action.get("y", random.randint(100, 1800))
            return {"coords": [x, y]}

        if action_type in ("find_element", "find_first_element", "tap_element"):
            return f"{random.randint(100, 900)},{random.randint(200, 1700)}"

        if action_type == "tap_first_visible":
            return {
                "tapped_label": action.get("candidates", [{}])[0].get("label", "btn_0"),
                "tapped_index": 0,
                "coords": f"{random.randint(100, 900)},{random.randint(200, 1700)}",
            }

        if action_type == "get_element_text":
            return f"SyntheticText_{random.randint(1000, 9999)}"

        if action_type == "screenshot":
            return {"path": f"/data/local/tmp/screenshot_{random.randint(1, 999)}.png"}

        if action_type == "shell":
            cmd = action.get("command", "echo ok")
            return f"synthetic_output_for: {cmd[:50]}"

        if action_type == "http_request":
            return {"status_code": 200, "body": '{"ok":true}'}

        if action_type == "get_device_info":
            return {
                "manufacturer": "Samsung",
                "model": "Galaxy S21",
                "android_version": "13",
                "sdk_int": 33,
                "display": f"{random.choice([1080, 1440])}x{random.choice([2340, 2560])}",
            }

        if action_type == "condition":
            return True

        if action_type in ("set_variable", "get_variable", "increment_variable"):
            return action.get("key", "")

        return None

    @staticmethod
    def _generate_error_message(action_type: str, action: dict[str, Any]) -> str:
        """Генерация реалистичного сообщения об ошибке."""
        errors: dict[str, list[str]] = {
            "find_element": [
                "Element not found: strategy=xpath selector='//Button[@text=\"Submit\"]'",
                "Element not found: strategy=id selector='com.app:id/btn_ok'",
                "UiAutomator dump timeout (10000ms)",
            ],
            "find_first_element": [
                "find_first_element: none of 3 candidates found within 8000ms",
                "UiAutomator connection reset during dump",
            ],
            "tap_element": [
                "tap_element: element not found: 'com.app:id/submit_btn'",
                "StaleElementException: element detached from DOM",
            ],
            "tap_first_visible": [
                "tap_first_visible: none of 2 candidates found within 5000ms",
            ],
            "wait_for_element_gone": [
                "wait_for_element_gone: element still visible after 15000ms",
            ],
            "scroll_to": [
                "scroll_to: element not found after 10 scrolls: '//RecyclerView/Item'",
            ],
            "http_request": [
                "java.net.ConnectException: Connection refused",
                "java.net.SocketTimeoutException: connect timed out",
                "HTTP 502 Bad Gateway",
            ],
            "assert": [
                "Assertion failed: element_exists — кнопка 'OK' не найдена",
                "Assertion failed: text_equals — ожидалось 'Готово', получено 'Загрузка...'",
            ],
            "launch_app": [
                "Activity not found for package com.app.broken",
            ],
            "condition": [
                "condition node has no 'check' or 'code'",
            ],
        }

        candidates = errors.get(action_type, [f"Ошибка выполнения узла '{action_type}'"])
        return random.choice(candidates)


class _NodeExecutionError(RuntimeError):
    """Внутренняя ошибка выполнения узла."""
    pass
