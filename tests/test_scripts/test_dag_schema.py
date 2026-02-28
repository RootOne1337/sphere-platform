# tests/test_scripts/test_dag_schema.py
# SPLIT-1 критерии готовности + MERGE-3 DAG contract tests.
from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from backend.schemas.dag import (
    VALID_ACTION_TYPES,
    DAGNode,
    DAGScript,
)
from backend.services.lua_safety import check_lua_safety

# ── Helpers ───────────────────────────────────────────────────────────────────

def _minimal_dag(**overrides) -> dict:
    """Минимально валидный DAG с двумя узлами: start → end."""
    base = {
        "version": "1.0",
        "name": "Test DAG",
        "nodes": [
            {"id": "start", "action": {"type": "start"}, "on_success": "end"},
            {"id": "end", "action": {"type": "end"}},
        ],
        "entry_node": "start",
    }
    base.update(overrides)
    return base


# ── MERGE-3: Contract: поля соответствуют Android DagRunner.kt ───────────────

class TestDagContract:
    def test_node_id_is_string(self):
        """MERGE-3: node.id — string, не int."""
        dag = DAGScript.model_validate(_minimal_dag())
        assert isinstance(dag.nodes[0].id, str)

    def test_action_type_is_in_valid_types(self):
        """MERGE-3: node.action.type — из VALID_ACTION_TYPES."""
        dag = DAGScript.model_validate(_minimal_dag())
        for node in dag.nodes:
            assert node.action["type"] in VALID_ACTION_TYPES

    def test_on_success_is_str_or_none(self):
        """MERGE-3: node.on_success — str | None, не list."""
        dag = DAGScript.model_validate(_minimal_dag())
        first = dag.nodes[0]
        assert isinstance(first.on_success, str)

    def test_nodes_is_list_not_dict(self):
        """MERGE-3: dag.nodes — list, не dict/map."""
        dag = DAGScript.model_validate(_minimal_dag())
        assert isinstance(dag.nodes, list)

    def test_valid_action_types_contains_all_expected(self):
        expected = {
            # Базовые действия (v1)
            "tap", "swipe", "type_text", "sleep", "find_element",
            "key_event", "lua", "screenshot", "condition", "start", "end",
            # Жизненный цикл приложений
            "launch_app", "stop_app", "clear_app_data",
            # Расширенные UI-элементы
            "find_first_element", "tap_first_visible", "tap_element",
            "get_element_text", "wait_for_element_gone", "scroll_to",
            # Жесты
            "long_press", "double_tap", "scroll",
            # Переменные контекста
            "set_variable", "get_variable", "increment_variable",
            # Системные
            "shell", "input_clear", "http_request", "open_url",
            "get_device_info", "assert",
        }
        assert VALID_ACTION_TYPES == expected


# ── SPLIT-1: Критерии готовности ─────────────────────────────────────────────

class TestCycleDetection:
    def test_dag_with_cycle_allowed_by_timeout(self):
        """DAG с циклом разрешён — защита через timeout_ms."""
        dag_dict = {
            "version": "1.0",
            "name": "Cyclic",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "a"},
                {"id": "a", "action": {"type": "tap", "x": 100, "y": 200}, "on_success": "b"},
                {"id": "b", "action": {"type": "tap", "x": 100, "y": 200}, "on_success": "a"},  # cycle!
            ],
            "entry_node": "start",
        }
        dag = DAGScript.model_validate(dag_dict)
        assert len(dag.nodes) == 3


class TestUnreachableNodes:
    def test_unreachable_node_raises_value_error(self):
        """Недостижимый узел → ValueError: Unreachable nodes."""
        dag_dict = {
            "version": "1.0",
            "name": "Unreachable",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "end"},
                {"id": "end", "action": {"type": "end"}},
                {"id": "orphan", "action": {"type": "tap", "x": 0, "y": 0}},  # unreachable!
            ],
            "entry_node": "start",
        }
        with pytest.raises(ValidationError) as exc_info:
            DAGScript.model_validate(dag_dict)
        assert "Unreachable" in str(exc_info.value) or "unreachable" in str(exc_info.value).lower()


class TestUnknownNodeReference:
    def test_on_success_references_unknown_node(self):
        """Ссылка на несуществующий узел → ValueError."""
        dag_dict = {
            "version": "1.0",
            "name": "Bad ref",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "nonexistent"},
                {"id": "end", "action": {"type": "end"}},
            ],
            "entry_node": "start",
        }
        with pytest.raises(ValidationError) as exc_info:
            DAGScript.model_validate(dag_dict)
        assert "nonexistent" in str(exc_info.value) or "unknown" in str(exc_info.value).lower()

    def test_entry_node_references_unknown(self):
        """entry_node не существует → ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            DAGScript.model_validate(_minimal_dag(entry_node="ghost"))
        assert "ghost" in str(exc_info.value)


class TestConditionAction:
    def test_condition_builds_graph_correctly(self):
        """ConditionAction с on_true/on_false корректно строит граф."""
        dag_dict = {
            "version": "1.0",
            "name": "Condition",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "check"},
                {
                    "id": "check",
                    "action": {
                        "type": "condition",
                        "check": "element_exists",
                        "params": {"selector": "//button"},
                        "on_true": "tap_btn",
                        "on_false": "end",
                    },
                },
                {"id": "tap_btn", "action": {"type": "tap", "x": 100, "y": 200}, "on_success": "end"},
                {"id": "end", "action": {"type": "end"}},
            ],
            "entry_node": "start",
        }
        dag = DAGScript.model_validate(dag_dict)
        condition_node = next(n for n in dag.nodes if n.id == "check")
        assert condition_node.action["type"] == "condition"
        assert condition_node.action["on_true"] == "tap_btn"
        assert condition_node.action["on_false"] == "end"

    def test_condition_with_unknown_on_true_raises(self):
        dag_dict = {
            "version": "1.0",
            "name": "Bad condition",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "check"},
                {
                    "id": "check",
                    "action": {
                        "type": "condition",
                        "check": "element_exists",
                        "params": {},
                        "on_true": "does_not_exist",
                        "on_false": "end",
                    },
                },
                {"id": "end", "action": {"type": "end"}},
            ],
            "entry_node": "start",
        }
        with pytest.raises(ValidationError):
            DAGScript.model_validate(dag_dict)


class TestLuaSafety:
    def test_os_execute_is_blocked(self):
        """os.execute() в Lua → отклонено как небезопасное."""
        violations = check_lua_safety('os.execute("rm -rf /")')
        assert any("os" in v for v in violations)

    def test_io_open_is_blocked(self):
        violations = check_lua_safety("io.open('/etc/passwd', 'r')")
        assert violations

    def test_loadfile_is_blocked(self):
        violations = check_lua_safety("loadfile('/tmp/evil.lua')")
        assert violations

    def test_require_is_blocked(self):
        violations = check_lua_safety("require('os')")
        assert violations

    def test_load_is_blocked(self):
        violations = check_lua_safety("load('return os.execute()')")
        assert violations

    def test_safe_lua_code_passes(self):
        """Безопасный Lua код проходит проверку."""
        safe_code = """
        local x = 10
        local y = 20
        local result = x + y
        print(result)
        """
        violations = check_lua_safety(safe_code)
        assert violations == []

    def test_case_insensitive_blocking(self):
        """Проверка case-insensitive: OS.Execute(), Os.Execute() → blocked."""
        violations = check_lua_safety("OS.Execute('whoami')")
        assert violations

    def test_lua_action_in_dag_blocks_unsafe_code(self):
        """ScriptAction с опасным кодом отклоняется при валидации DAG."""
        dag_dict = {
            "version": "1.0",
            "name": "Evil DAG",
            "nodes": [
                {"id": "start", "action": {"type": "start"}, "on_success": "evil"},
                {
                    "id": "evil",
                    "action": {
                        "type": "lua",
                        "code": "os.execute('id')",
                    },
                    "on_success": "end",
                },
                {"id": "end", "action": {"type": "end"}},
            ],
            "entry_node": "start",
        }
        with pytest.raises(ValidationError) as exc_info:
            DAGScript.model_validate(dag_dict)
        assert "Unsafe" in str(exc_info.value) or "Blocked" in str(exc_info.value)


class TestDagPerformance:
    def test_500_nodes_validates_under_100ms(self):
        """500 узлов в DAG: валидация < 100ms."""
        nodes = [{"id": "start", "action": {"type": "start"}, "on_success": "n1"}]
        for i in range(1, 499):
            nodes.append({
                "id": f"n{i}",
                "action": {"type": "tap", "x": 0, "y": 0},
                "on_success": f"n{i + 1}",
            })
        nodes.append({"id": "n499", "action": {"type": "end"}})

        dag_dict = {
            "version": "1.0",
            "name": "Large DAG",
            "nodes": nodes,
            "entry_node": "start",
        }

        start = time.perf_counter()
        dag = DAGScript.model_validate(dag_dict)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert dag is not None
        assert elapsed_ms < 100, f"Validation took {elapsed_ms:.1f}ms (limit: 100ms)"


class TestActionValidation:
    def test_unknown_action_type_rejected(self):
        """Неизвестный тип action отклоняется."""
        with pytest.raises(ValidationError):
            DAGNode(
                id="node1",
                action={"type": "nonexistent_action", "x": 100},
            )

    def test_minimal_valid_dag(self):
        """Минимальный валидный DAG (2 узла) проходит валидацию."""
        dag = DAGScript.model_validate(_minimal_dag())
        assert len(dag.nodes) == 2
        assert dag.entry_node == "start"

    def test_dag_requires_at_least_2_nodes(self):
        """DAG с 1 узлом → ValidationError (min_length=2)."""
        with pytest.raises(ValidationError):
            DAGScript.model_validate({
                "version": "1.0",
                "name": "Too small",
                "nodes": [{"id": "start", "action": {"type": "start"}}],
                "entry_node": "start",
            })

    def test_node_id_pattern_enforced(self):
        """node.id должен соответствовать ^[a-zA-Z_][\\w-]{0,63}$."""
        with pytest.raises(ValidationError):
            DAGNode(
                id="123invalid",  # starts with digit
                action={"type": "start"},
            )
