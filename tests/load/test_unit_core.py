# -*- coding: utf-8 -*-
"""
Unit-тесты для core/ модулей (без сервера).

Проверяют: IdentityFactory, MetricsCollector, MessageFactory,
AgentBehavior, ReportGenerator, CriteriaEvaluator.
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.load.core.identity_factory import IdentityFactory
from tests.load.core.metrics_collector import MetricsCollector, StepResult
from tests.load.core.orchestrator import CriteriaEvaluator
from tests.load.core.report_generator import ReportGenerator
from tests.load.core.virtual_agent import AgentBehavior
from tests.load.protocols.message_factory import MessageFactory

# ===================================================================
# IdentityFactory
# ===================================================================


class TestIdentityFactory:
    """Тесты фабрики идентичностей."""

    def test_create_deterministic(self) -> None:
        """Одинаковый seed → одинаковые идентичности."""
        f1 = IdentityFactory(org_id="test-org", seed=42)
        f2 = IdentityFactory(org_id="test-org", seed=42)
        a1 = f1.create(0)
        a2 = f2.create(0)
        assert a1.device_id == a2.device_id
        assert a1.serial == a2.serial
        assert a1.fingerprint == a2.fingerprint

    def test_create_unique(self) -> None:
        """Разные индексы → разные device_id."""
        f = IdentityFactory(org_id="test-org", seed=42)
        ids = {f.create(i).device_id for i in range(100)}
        assert len(ids) == 100

    def test_create_batch(self) -> None:
        """Batch создание нужного кол-ва."""
        f = IdentityFactory(org_id="test-org", seed=1)
        batch = f.create_batch(0, 50)
        assert len(batch) == 50
        assert len({a.device_id for a in batch}) == 50

    def test_model_variation(self) -> None:
        """Модели устройств варьируются."""
        f = IdentityFactory(org_id="test-org", seed=42)
        models = {f.create(i).model for i in range(100)}
        assert len(models) > 1  # Не все одинаковые

    def test_identity_fields_not_empty(self) -> None:
        """Все поля заполнены."""
        f = IdentityFactory(org_id="test-org", seed=42)
        a = f.create(0)
        assert a.device_id
        assert a.serial
        assert a.fingerprint
        assert a.model
        assert a.android_version


# ===================================================================
# MetricsCollector
# ===================================================================


class TestMetricsCollector:
    """Тесты сборщика метрик."""

    def test_counter_inc(self) -> None:
        m = MetricsCollector()
        m.inc("test_counter")
        m.inc("test_counter", 5)
        assert m.counter("test_counter") == 6

    def test_gauge_set(self) -> None:
        m = MetricsCollector()
        m.set_gauge("cpu", 42.5)
        assert m.gauge("cpu") == 42.5
        m.set_gauge("cpu", 99.0)
        assert m.gauge("cpu") == 99.0

    def test_histogram_record(self) -> None:
        m = MetricsCollector()
        for v in [10, 20, 30, 40, 50]:
            m.record("latency", float(v))
        summary = m.histogram_summary("latency")
        assert "p50" in summary
        assert "p99" in summary
        assert summary["count"] == 5

    def test_snapshot(self) -> None:
        m = MetricsCollector()
        m.inc("requests")
        m.set_gauge("active", 10.0)
        m.record("lat", 100.0)
        snap = m.snapshot()
        assert "counters" in snap
        assert "gauges" in snap
        assert "histograms" in snap
        assert snap["counters"]["requests"] == 1
        assert snap["gauges"]["active"] == 10.0

    def test_save_json(self, tmp_path: Path) -> None:
        m = MetricsCollector()
        m.inc("x", 3)
        path = tmp_path / "metrics.json"
        m.save_json(path)
        assert path.exists()
        data = json.loads(path.read_text())
        # save_json → to_dict → final_snapshot → counters
        assert data["final_snapshot"]["counters"]["x"] == 3


# ===================================================================
# MessageFactory
# ===================================================================


class TestMessageFactory:
    """Тесты фабрики сообщений."""

    def test_auth_message(self) -> None:
        msg = json.loads(MessageFactory.auth("my-token"))
        assert msg["token"] == "my-token"

    def test_pong_with_ts(self) -> None:
        msg = json.loads(MessageFactory.pong(ts=1234567890.123))
        assert msg["type"] == "pong"
        assert msg["ts"] == 1234567890.123
        assert "battery" in msg
        assert "ram_mb" in msg
        assert "stream" in msg

    def test_pong_without_ts(self) -> None:
        msg = json.loads(MessageFactory.pong())
        assert msg["type"] == "pong"
        assert "ts" in msg

    def test_telemetry(self) -> None:
        msg = json.loads(MessageFactory.telemetry(battery=80, cpu=25.3))
        assert msg["type"] == "telemetry"
        assert msg["battery"] == 80
        assert msg["cpu"] == 25.3
        assert "ram_mb" in msg
        assert "stream" in msg

    def test_telemetry_random_values(self) -> None:
        """Без аргументов — случайные значения в диапазоне."""
        msg = json.loads(MessageFactory.telemetry())
        assert 20 <= msg["battery"] <= 95
        assert 5.0 <= msg["cpu"] <= 80.0

    def test_task_progress(self) -> None:
        msg = json.loads(MessageFactory.task_progress("t1", "n3", 3, 12))
        assert msg["type"] == "task_progress"
        assert msg["task_id"] == "t1"
        assert msg["current_node"] == "n3"
        assert msg["nodes_done"] == 3
        assert msg["total_nodes"] == 12

    def test_command_result(self) -> None:
        msg = json.loads(MessageFactory.command_result("cmd-1", status="completed"))
        assert "type" not in msg  # Формат command_result без поля type
        assert msg["command_id"] == "cmd-1"
        assert msg["status"] == "completed"

    def test_command_ack(self) -> None:
        msg = json.loads(MessageFactory.command_ack("cmd-2"))
        assert "type" not in msg  # Реальный APK не шлёт type в ack
        assert msg["command_id"] == "cmd-2"
        assert msg["status"] == "received"

    def test_device_register_payload(self) -> None:
        p = MessageFactory.device_register_payload(
            device_id="d1", serial="s1", model="Pixel",
            android_version="14", fingerprint="fp1",
        )
        assert p["device_id"] == "d1"
        assert p["app_version"] == "2.1.0"

    def test_server_ping(self) -> None:
        msg = json.loads(MessageFactory.server_ping())
        assert msg["type"] == "ping"
        assert "ts" in msg

    def test_server_execute_dag(self) -> None:
        dag = {"version": "1.0", "nodes": [], "entry_node": "n1"}
        msg = json.loads(MessageFactory.server_execute_dag(dag, command_id="c1", task_id="t1"))
        assert msg["type"] == "EXECUTE_DAG"
        assert msg["command_id"] == "c1"
        assert msg["payload"]["task_id"] == "t1"
        assert msg["payload"]["dag"] == dag


# ===================================================================
# AgentBehavior
# ===================================================================


class TestAgentBehavior:
    """Тесты конфигурации поведения."""

    def test_defaults(self) -> None:
        b = AgentBehavior()
        assert b.heartbeat_interval == 30.0
        assert b.task_success_rate == 0.80
        assert b.enable_vpn is True

    def test_custom(self) -> None:
        b = AgentBehavior(heartbeat_interval=5.0, enable_vpn=False)
        assert b.heartbeat_interval == 5.0
        assert b.enable_vpn is False


# ===================================================================
# CriteriaEvaluator
# ===================================================================


class TestCriteriaEvaluator:
    """Тесты оценки pass/fail."""

    def test_pass_all(self) -> None:
        snap = {"gauges": {"fleet_availability": 99.0}, "counters": {}, "histograms": {}}
        violations = CriteriaEvaluator.evaluate(
            {"fleet_availability_gte": 97.0}, snap
        )
        assert violations == []

    def test_fail_gte(self) -> None:
        snap = {"gauges": {"fleet_availability": 90.0}, "counters": {}, "histograms": {}}
        violations = CriteriaEvaluator.evaluate(
            {"fleet_availability_gte": 97.0}, snap
        )
        assert len(violations) == 1
        assert "gte" in violations[0]

    def test_fail_lte(self) -> None:
        snap = {
            "gauges": {},
            "counters": {},
            "histograms": {
                "ws_connect_latency": {"p99": 12000.0}
            },
        }
        violations = CriteriaEvaluator.evaluate(
            {"ws_connect_latency_p99_lte": 5000}, snap
        )
        assert len(violations) == 1

    def test_pass_lte(self) -> None:
        snap = {
            "gauges": {},
            "counters": {},
            "histograms": {
                "ws_connect_latency": {"p99": 3000.0}
            },
        }
        violations = CriteriaEvaluator.evaluate(
            {"ws_connect_latency_p99_lte": 5000}, snap
        )
        assert violations == []


# ===================================================================
# ReportGenerator
# ===================================================================


class TestReportGenerator:
    """Тесты генератора HTML-отчёта."""

    def test_html_generation(self) -> None:
        data = {
            "test_name": "unit-test",
            "overall_passed": True,
            "total_duration_sec": 10.0,
            "steps": [
                {
                    "name": "step-32",
                    "target": 32,
                    "actual_online": 30,
                    "fleet_availability": 97.5,
                    "duration_sec": 10.0,
                    "passed": True,
                    "violations": [],
                    "snapshot": {},
                },
            ],
        }
        html_output = ReportGenerator.to_html(data)
        assert "unit-test" in html_output
        assert "PASS" in html_output
        assert "step-32" in html_output
        assert "<canvas" in html_output
        assert "Chart" in html_output

    def test_html_fail_status(self) -> None:
        data = {
            "test_name": "fail-test",
            "overall_passed": False,
            "total_duration_sec": 5.0,
            "steps": [],
        }
        html_output = ReportGenerator.to_html(data)
        assert "FAIL" in html_output


# ===================================================================
# StepResult
# ===================================================================


class TestStepResult:
    """Тесты dataclass StepResult."""

    def test_creation(self) -> None:
        sr = StepResult(
            step_name="test",
            target_agents=100,
            actual_online=95,
            fleet_availability=95.0,
            duration_sec=60.0,
            passed=True,
        )
        assert sr.step_name == "test"
        assert sr.violations == []
        assert sr.snapshot == {}
