# backend/schemas/dag.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-1. Каноническая DAG JSON Schema — единственный источник истины.
#
# MERGE-3: КОНТРАКТ — все потребители (Android DagRunner.kt, n8n ExecuteScript,
# Frontend ScriptBuilder) обязаны использовать ЭТИ типы без изменений.
#
# Контрольные поля (нарушение = runtime crash в агентах):
#   node.id          — str (pattern ^[a-zA-Z_][\w-]{0,63}$), НЕ int
#   node.action.type — Literal из NodeAction union
#   node.on_success  — str | None (ID узла), НЕ array
#   dag.nodes        — list[DAGNode], НЕ dict/map
from __future__ import annotations

import re
import sys
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

# ─────── Node Actions ───────────────────────────────────────────────────────


class TapAction(BaseModel):
    type: Literal["tap"]
    x: int = Field(ge=0, le=3840)
    y: int = Field(ge=0, le=2160)


class SwipeAction(BaseModel):
    type: Literal["swipe"]
    x1: int = Field(ge=0, le=3840)
    y1: int = Field(ge=0, le=2160)
    x2: int = Field(ge=0, le=3840)
    y2: int = Field(ge=0, le=2160)
    duration_ms: int = Field(default=300, ge=50, le=10000)


class TypeTextAction(BaseModel):
    type: Literal["type_text"]
    text: str = Field(max_length=1000)
    clear_first: bool = False


class SleepAction(BaseModel):
    type: Literal["sleep"]
    ms: int = Field(ge=10, le=300_000)


class FindElementAction(BaseModel):
    type: Literal["find_element"]
    selector: str = Field(max_length=500, description="XPath or resource-id or text")
    strategy: Literal["xpath", "id", "text", "desc"] = "text"
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    fail_if_not_found: bool = True


class KeyEventAction(BaseModel):
    type: Literal["key_event"]
    keycode: int = Field(ge=0, le=400)


class ScriptAction(BaseModel):
    """Lua-скрипт. Код проверяется на безопасность при валидации DAG."""
    type: Literal["lua"]
    code: str = Field(max_length=50_000)

    @model_validator(mode="after")
    def validate_lua_safety(self) -> "ScriptAction":
        from backend.services.lua_safety import check_lua_safety
        violations = check_lua_safety(self.code)
        if violations:
            raise ValueError(f"Unsafe Lua code: {violations}")
        return self


class ScreenshotAction(BaseModel):
    type: Literal["screenshot"]
    save_as: str | None = Field(None, pattern=r'^[\w\-]+$')


class ConditionAction(BaseModel):
    type: Literal["condition"]
    check: Literal["element_exists", "text_contains", "battery_above"]
    params: dict
    on_true: str   # next node id
    on_false: str  # next node id


class StartAction(BaseModel):
    type: Literal["start"]


class EndAction(BaseModel):
    type: Literal["end"]
    status: Literal["success", "failure"] = "success"


# ── Discriminated union всех типов ──────────────────────────────────────────

Action = Annotated[
    Union[
        TapAction,
        SwipeAction,
        TypeTextAction,
        SleepAction,
        FindElementAction,
        KeyEventAction,
        ScriptAction,
        ScreenshotAction,
        ConditionAction,
        StartAction,
        EndAction,
    ],
    Field(discriminator="type"),
]

# Canonical set of valid action types — экспортируется для contract-тестов
VALID_ACTION_TYPES: frozenset[str] = frozenset({
    "tap", "swipe", "type_text", "sleep", "find_element",
    "key_event", "lua", "screenshot", "condition", "start", "end",
})


# ─────── DAG Node & Graph ────────────────────────────────────────────────────


class DAGNode(BaseModel):
    """Узел DAG-графа. id — строка, не int (MERGE-3 contract)."""
    id: str = Field(pattern=r'^[a-zA-Z_][\w-]{0,63}$')
    action: Action
    on_success: str | None = None   # ID следующего узла при успехе
    on_failure: str | None = None   # ID узла при ошибке
    retry: int = Field(default=0, ge=0, le=5)
    timeout_ms: int = Field(default=30_000, ge=100, le=3_600_000)


class DAGScript(BaseModel):
    """
    Корневой объект DAG-сценария.

    Ограничения, проверяемые при валидации:
      1. entry_node должен существовать в nodes
      2. Все on_success / on_failure ссылки должны существовать
      3. ConditionAction.on_true / on_false должны существовать
      4. Граф ацикличен (DFS cycle detection)
      5. Все узлы достижимы от entry_node
      6. Lua-код в ScriptAction проходит проверку lua_safety
    """
    version: Literal["1.0"] = "1.0"
    name: str = Field(max_length=255)
    description: str | None = Field(None, max_length=2000)
    nodes: list[DAGNode] = Field(min_length=2, max_length=500)
    entry_node: str

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
            # ConditionAction ссылки
            if isinstance(node.action, ConditionAction):
                for ref in (node.action.on_true, node.action.on_false):
                    if ref not in node_ids:
                        raise ValueError(
                            f"Condition node '{node.id}' refs unknown '{ref}'"
                        )

        # 3+4. DFS: обнаружение циклов + сбор достижимых узлов
        self._check_no_infinite_loops(node_ids)

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
            if isinstance(node.action, ConditionAction):
                adj[node.id] += [node.action.on_true, node.action.on_false]
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
        # Итеративный DFS с явным стеком вместо рекурсии
        for start in all_ids:
            if start in visited:
                continue
            # stack: (node, path_set)
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
