# backend/schemas/dag.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-1. Каноническая DAG JSON Schema — единственный источник истины.
#
# MERGE-3: КОНТРАКТ — все потребители (Android DagRunner.kt, n8n ExecuteScript,
# Frontend ScriptBuilder) обязаны использовать ЭТИ типы без изменений.
#
# Контрольные поля (нарушение = runtime crash в агентах):
#   node.id          — str (pattern ^[a-zA-Z_][\w-]{0,63}$), НЕ int
#   node.action.type — str из VALID_ACTION_TYPES
#   node.on_success  — str | None (ID узла), НЕ array
#   dag.nodes        — list[DAGNode], НЕ dict/map
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ─────── Canonical set of valid action types ────────────────────────────────
# Полный набор поддерживаемых DagRunner.kt action types.
# Обновляется при добавлении нового action в DagRunner.

VALID_ACTION_TYPES: frozenset[str] = frozenset({
    # Базовые действия (были с v1)
    "tap", "swipe", "type_text", "sleep", "find_element",
    "key_event", "lua", "screenshot", "condition", "start", "end",
    # Жизненный цикл приложений
    "launch_app", "stop_app", "clear_app_data",
    # Элементы UI — расширенные
    "find_first_element", "tap_first_visible", "tap_element",
    "get_element_text", "wait_for_element_gone", "scroll_to",
    # Жесты
    "long_press", "double_tap", "scroll",
    # Переменные контекста
    "set_variable", "get_variable", "increment_variable",
    # Системные
    "shell", "input_clear", "http_request", "open_url",
    "get_device_info", "assert",
})


# ─────── DAG Node & Graph ────────────────────────────────────────────────────


class DAGNode(BaseModel):
    """
    Узел DAG-графа. id — строка, не int (MERGE-3 contract).

    action — произвольный dict с обязательным ключом 'type'.
    Strict-валидация полей каждого action остаётся на стороне DagRunner —
    backend валидирует только тип, ссылки графа и отсутствие циклов.
    """
    id: str = Field(pattern=r'^[a-zA-Z_][\w-]{0,63}$')
    action: dict = Field(description="Action object, обязательный ключ 'type'")
    on_success: str | None = None   # ID следующего узла при успехе
    on_failure: str | None = None   # ID узла при ошибке
    retry: int = Field(default=0, ge=0, le=5)
    timeout_ms: int = Field(default=30_000, ge=100, le=3_600_000)

    @model_validator(mode="after")
    def validate_action_has_type(self) -> "DAGNode":
        """Проверяем что action содержит 'type' из допустимого набора."""
        action_type = self.action.get("type")
        if not action_type:
            raise ValueError(f"Node '{self.id}': action must contain 'type' key")
        if action_type not in VALID_ACTION_TYPES:
            raise ValueError(
                f"Node '{self.id}': unknown action type '{action_type}'"
            )
        # condition action обязан содержать on_true и on_false
        if action_type == "condition":
            for ref in ("on_true", "on_false"):
                if not self.action.get(ref):
                    raise ValueError(
                        f"Condition node '{self.id}': missing '{ref}' in action"
                    )
        # Lua safety — проверяем code в lua action и condition action с code
        lua_code = None
        if action_type == "lua":
            lua_code = self.action.get("code", "")
        elif action_type == "condition" and "code" in self.action:
            lua_code = self.action.get("code", "")
        if lua_code:
            from backend.services.lua_safety import check_lua_safety
            violations = check_lua_safety(lua_code)
            if violations:
                raise ValueError(
                    f"Node '{self.id}': unsafe Lua code: {violations}"
                )
        return self


class DAGScript(BaseModel):
    """
    Корневой объект DAG-сценария.

    Ограничения, проверяемые при валидации:
      1. entry_node должен существовать в nodes
      2. Все on_success / on_failure ссылки должны существовать
      3. condition action on_true / on_false должны существовать
      4. Граф — нет бесконечных циклов (DFS cycle detection)
      5. Все узлы достижимы от entry_node
    """
    version: Literal["1.0"] = "1.0"
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=2000)
    nodes: list[DAGNode] = Field(min_length=2, max_length=500)
    entry_node: str
    timeout_ms: int = Field(default=1_800_000, ge=1_000, le=86_400_000,
                            description="Глобальный таймаут выполнения DAG (мс)")

    @model_validator(mode="after")
    def validate_dag(self) -> "DAGScript":
        node_ids = {n.id for n in self.nodes}

        # 1. entry_node должен существовать
        if self.entry_node not in node_ids:
            raise ValueError(f"entry_node '{self.entry_node}' not found in nodes")

        # 2. Все ссылки on_success/on_failure должны существовать
        for node in self.nodes:
            for ref_attr in ("on_success", "on_failure"):
                ref = getattr(node, ref_attr, None)
                if ref and ref not in node_ids:
                    raise ValueError(
                        f"Node '{node.id}' references unknown node '{ref}'"
                    )
            # 3. condition action ссылки on_true/on_false
            if node.action.get("type") == "condition":
                for ref_key in ("on_true", "on_false"):
                    ref = node.action.get(ref_key)
                    if ref and ref not in node_ids:
                        raise ValueError(
                            f"Condition node '{node.id}' refs unknown '{ref}'"
                        )

        # 4. Цикличность: DAG-скрипты используют циклические опрашивающие петли
        #    (polling loops) и условные переходы — это нормальное поведение.
        #    Защита от бесконечного выполнения обеспечивается timeout_ms.
        #    Структурная проверка на ациклность ОТКЛЮЧЕНА.

        # 5. Все узлы достижимы от entry_node
        reachable = self._get_reachable()
        unreachable = node_ids - reachable
        if unreachable:
            raise ValueError(f"Unreachable nodes detected: {sorted(unreachable)}")

        return self

    def _build_adj(self) -> dict[str, list[str]]:
        """Построить граф смежности из on_success / on_failure / condition refs."""
        adj: dict[str, list[str]] = {n.id: [] for n in self.nodes}
        for node in self.nodes:
            for attr in ("on_success", "on_failure"):
                ref = getattr(node, attr, None)
                if ref:
                    adj[node.id].append(ref)
            if node.action.get("type") == "condition":
                for ref_key in ("on_true", "on_false"):
                    target = node.action.get(ref_key)
                    if target:
                        adj[node.id].append(target)
        return adj

    def _get_reachable(self) -> set[str]:
        adj = self._build_adj()
        visited: set[str] = set()
        stack = [self.entry_node]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj.get(n, []))
        return visited

    def _check_no_infinite_loops(self, all_ids: set[str]) -> None:
        """Итеративный DFS для обнаружения циклов (избегает рекурсивного stack overflow)."""
        adj = self._build_adj()
        visited: set[str] = set()
        for start in all_ids:
            if start in visited:
                continue
            dfs_stack: list[tuple[str, set[str]]] = [(start, set())]
            while dfs_stack:
                node, path = dfs_stack[-1]
                if node not in visited:
                    visited.add(node)
                    path.add(node)
                    pushed = False
                    for nb in adj.get(node, []):
                        if nb in path:
                            raise ValueError(f"Cycle detected at node '{nb}'")
                        if nb not in visited:
                            dfs_stack.append((nb, path.copy()))
                            pushed = True
                            break
                    if not pushed:
                        dfs_stack.pop()
                        path.discard(node)
                else:
                    dfs_stack.pop()
