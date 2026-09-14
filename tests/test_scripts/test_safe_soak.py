"""The overnight harness must refuse false success and stop on unknown outcomes."""

import copy
import json
from unittest.mock import AsyncMock

import pytest

from scripts.pilot.android_soak import (
    EXPECTED_NODES,
    Runner,
    SoakFailure,
    safe_dag,
    validate_result,
)
from scripts.pilot.summarize_soak import summarize


def receipt():
    logs = [{"node_id": n, "success": True} for n in EXPECTED_NODES]
    next(n for n in logs if n["node_id"] == "echo")["output"] = "SPHERE_SAFE_SOAK_OK\n"
    next(n for n in logs if n["node_id"] == "sdk")["output"] = "28\n"
    return {"device_id": "device", "script_version_id": "version", "status": "completed",
            "finished_at": "2026-09-14T00:00:00Z",
            "result": {"success": True, "node_logs": logs, "nodes_executed": len(logs)}}


def test_reviewed_fixture_is_canonical_and_bounded():
    dag = safe_dag()
    assert dag["timeout_ms"] == 45000
    assert len(dag["nodes"]) == 14
    assert all(node["retry"] == 0 for node in dag["nodes"])


@pytest.mark.parametrize("defect", ["wrong_device", "wrong_version", "not_terminal", "missing_node",
                                    "duplicate_node", "failed_node", "false_echo", "empty_result"])
def test_nominal_completed_status_cannot_hide_bad_native_receipt(defect):
    good = receipt()
    assert validate_result(good, "device", "version") == good["result"]
    bad = copy.deepcopy(good)
    if defect == "wrong_device":
        bad["device_id"] = "other"
    elif defect == "wrong_version":
        bad["script_version_id"] = "other"
    elif defect == "not_terminal":
        bad["status"] = "running"
    elif defect == "missing_node":
        bad["result"]["node_logs"].pop()
    elif defect == "duplicate_node":
        bad["result"]["node_logs"].append(bad["result"]["node_logs"][0])
    elif defect == "failed_node":
        bad["result"]["node_logs"][3]["success"] = False
    elif defect == "false_echo":
        bad["result"]["node_logs"][9]["output"] = "different"
    else:
        bad["result"] = None
    with pytest.raises(SoakFailure):
        validate_result(bad, "device", "version")


async def test_unknown_batch_post_is_not_retried_or_recorded_as_success(tmp_path):
    config = {"devices": [{"id": "85f2f935-7739-400e-9389-0d71227e8f0a"}],
              "package": "com.sphereplatform.agent.pilot.debug", "script_id": "script", "version_id": "version"}
    runner = Runner(config, tmp_path, 120)
    runner.no_existing_tasks = AsyncMock()
    runner.request = AsyncMock(side_effect=TimeoutError("response lost after possible commit"))
    with pytest.raises(TimeoutError):
        await runner.batch(1)
    runner.request.assert_awaited_once()
    assert runner.state["tasks_passed"] == 0
    assert runner.active_batch is None


async def test_failure_finishes_with_diagnostics_and_stops_admission(tmp_path):
    config = {"devices": [{"id": "85f2f935-7739-400e-9389-0d71227e8f0a"}],
              "package": "com.sphereplatform.agent.pilot.debug", "script_id": "script", "version_id": "version"}
    runner = Runner(config, tmp_path, 120)
    runner.authenticate = AsyncMock()
    runner.check_script = AsyncMock()
    runner.no_existing_tasks = AsyncMock()
    runner.sample = AsyncMock()
    runner.cycle = AsyncMock(side_effect=SoakFailure("APK process restarted"))
    runner.diagnostics = AsyncMock()
    assert await runner.run() == 1
    runner.cycle.assert_awaited_once()
    runner.diagnostics.assert_awaited_once()
    assert runner.state["status"] == "failed"
    assert runner.state["cycles_passed"] == 0


async def test_modified_pipeline_is_rejected_before_run_admission(tmp_path):
    config = {"devices": [{"id": "85f2f935-7739-400e-9389-0d71227e8f0a"}],
              "package": "com.sphereplatform.agent.pilot.debug", "script_id": "script",
              "version_id": "version", "pipeline_id": "pipeline"}
    runner = Runner(config, tmp_path, 120)
    runner.request = AsyncMock(return_value={"steps": [{"type": "unreviewed"}]})
    with pytest.raises(SoakFailure, match="Pipeline fixture changed"):
        await runner.pipeline_controls()
    runner.request.assert_awaited_once_with("GET", "/api/v1/pipelines/pipeline")
    assert runner.state["pipeline_controls_passed"] == 0


def test_running_summary_does_not_claim_completion_and_preserves_partial_log(tmp_path):
    (tmp_path / "status.json").write_text(json.dumps({"status": "running", "devices": ["one"]}))
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event": "command", "seconds": 0.5}) + '\n{"partial":')
    report = summarize(tmp_path)
    assert report["status"]["status"] == "running"
    assert report["incomplete_event_lines"] == 1
    assert report["command_seconds"]["count"] == 1
