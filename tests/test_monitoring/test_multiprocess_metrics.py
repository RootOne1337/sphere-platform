"""Real child processes verify aggregation, cardinality and worker retirement."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from prometheus_client.parser import text_string_to_metric_families

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).parent / "fixtures" / "multiprocess_worker.py"


def wait_for(path: Path, workers: list[subprocess.Popen]) -> None:
    deadline = time.monotonic() + 15
    while not path.exists():
        assert all(worker.poll() is None for worker in workers), "Worker exited before receipt"
        assert time.monotonic() < deadline, f"Missing receipt: {path.name}"
        time.sleep(0.02)


def samples(body: str) -> dict:
    result = {}
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            assert key not in result, f"Duplicate exposition sample: {key}"
            result[key] = sample.value
    return result


def value(body: str, name: str, **labels: str) -> float:
    return samples(body)[(name, tuple(sorted(labels.items())))]


def test_four_workers_aggregate_retire_and_replace(tmp_path):
    directory = tmp_path / "metrics"
    directory.mkdir()
    env = dict(os.environ, PROMETHEUS_MULTIPROC_DIR=str(directory), PYTHONPATH=str(ROOT))
    env.pop("prometheus_multiproc_dir", None)
    workers = []

    def start(index):
        worker = subprocess.Popen(
            [sys.executable, str(WORKER), str(tmp_path), str(index)],
            env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        workers.append(worker)
        wait_for(tmp_path / f"ready-{index}.json", [item for item in workers[:-1] if item.poll() is None] + [worker])
        return worker

    def scrape(index):
        receipt = tmp_path / f"metrics-{index}.txt"
        receipt.unlink(missing_ok=True)
        (tmp_path / f"scrape-{index}").touch()
        wait_for(receipt, [worker for worker in workers if worker.poll() is None])
        return receipt.read_text()

    try:
        for index in range(4):
            start(index)
        for index in range(4):
            body = scrape(index)
            assert value(body, "sphere_metrics_worker_processes") == 4
            assert value(body, "sphere_db_pool_size") == 40
            assert value(body, "sphere_db_pool_checked_out") == 10
            assert value(body, "sphere_http_requests_total", method="GET", endpoint="/canary/{id}", status_code="200") == 10
            assert value(body, "sphere_http_request_duration_seconds_count", method="GET", endpoint="/canary/{id}") == 10
            assert value(body, "sphere_http_request_duration_seconds_bucket", method="GET", endpoint="/canary/{id}", le="0.25") == 10
            assert value(body, "sphere_http_request_duration_seconds_sum", method="GET", endpoint="/canary/{id}") == pytest.approx(2)
            assert value(body, "sphere_continuous_stage_duration_seconds_count", stage="redis_lease_operation", outcome="returned") == 10
            assert value(body, "sphere_continuous_stage_duration_seconds_sum", stage="redis_lease_operation", outcome="returned") == pytest.approx(1.25)
            assert value(body, "sphere_continuous_stage_duration_seconds_bucket", stage="redis_lease_operation", outcome="returned", le="0.25") == 10
            assert value(body, "sphere_continuous_stage_duration_seconds_bucket", stage="redis_lease_operation", outcome="returned", le="0.1") == 0
            continuous_pairs = {tuple(sorted(sample.labels.items()))
                                for family in text_string_to_metric_families(body)
                                for sample in family.samples
                                if sample.name == "sphere_continuous_stage_duration_seconds_count"}
            assert len(continuous_pairs) == 21
            assert value(body, "sphere_fleet_stream_backend_ingress_frames_total") == 4000
            assert value(body, "sphere_fleet_stream_backend_ingress_packets_by_nal_total", nal_type="idr") == 4000
            assert value(body, "sphere_fleet_stream_active_viewers") == 10
            assert 'device_id=' not in body
            assert "sphere_stream_fps" not in body
            assert "process_cpu_seconds_total" not in body
            # Container resources are read at scrape time once, never multiplied
            # by the four worker registries. Windows has no cgroup: availability=0.
            resource_samples = [(key, number) for key, number in samples(body).items()
                                if key[0] == "sphere_container_resource_available"]
            assert len(resource_samples) == 4
            assert all("pid" not in dict(key[1]) for key, _ in resource_samples)
        # Bounded mmap: 4 process files per worker, despite 4,000 device IDs.
        files = list(directory.glob("*.db"))
        assert len(files) <= 16
        assert sum(path.stat().st_size for path in files) <= 16 * 65536

        retired_pid = json.loads((tmp_path / "ready-3.json").read_text())["pid"]
        (tmp_path / "stop-3").touch()
        assert workers[3].wait(timeout=5) == 0
        # Gunicorn invokes the hook in the master AFTER the child exited.
        # Doing it in the live child is invalid on Windows (open mmap handle).
        retired = subprocess.run(
            [sys.executable, "-c", "import sys; from backend.gunicorn_conf import child_exit; "
             "child_exit(None, type('Worker', (), {'pid': int(sys.argv[1])})())", str(retired_pid)],
            env=env, cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
        assert retired.returncode == 0, retired.stderr
        body = scrape(0)
        assert value(body, "sphere_metrics_worker_processes") == 3
        assert value(body, "sphere_db_pool_size") == 30
        assert value(body, "sphere_db_pool_checked_out") == 6
        assert value(body, "sphere_fleet_stream_active_viewers") == 6
        assert value(body, "sphere_http_requests_total", method="GET", endpoint="/canary/{id}", status_code="200") == 10
        assert value(body, "sphere_continuous_stage_duration_seconds_count", stage="redis_lease_operation", outcome="returned") == 10
        assert not list(directory.glob(f"gauge_live*_{retired_pid}.db"))
        assert (directory / f"counter_{retired_pid}.db").exists()

        start(4)
        body = scrape(4)
        assert value(body, "sphere_metrics_worker_processes") == 4
        assert value(body, "sphere_db_pool_size") == 40
        assert value(body, "sphere_db_pool_checked_out") == 11
        assert value(body, "sphere_http_requests_total", method="GET", endpoint="/canary/{id}", status_code="200") == 15
        assert value(body, "sphere_http_request_duration_seconds_count", method="GET", endpoint="/canary/{id}") == 15
        assert value(body, "sphere_continuous_stage_duration_seconds_count", stage="redis_lease_operation", outcome="returned") == 15
        assert value(body, "sphere_fleet_stream_backend_ingress_frames_total") == 5000
    finally:
        for index in range(len(workers)):
            (tmp_path / f"stop-{index}").touch()
        for worker in workers:
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
            errors = worker.stderr.read().decode(errors="replace")
            worker.stderr.close()
            assert worker.returncode == 0, errors


def test_single_process_keeps_device_metric_contract():
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    env.pop("PROMETHEUS_MULTIPROC_DIR", None)
    env.pop("prometheus_multiproc_dir", None)
    result = subprocess.run(
        [sys.executable, "-c", "from backend import metrics; from prometheus_client import REGISTRY; "
         "metrics.stream_fps.labels(device_id='test').set(30); "
         "assert REGISTRY.get_sample_value('sphere_stream_fps', {'device_id':'test'}) == 30; "
         "metrics.cleanup_stream_metrics('test'); "
         "assert REGISTRY.get_sample_value('sphere_stream_fps', {'device_id':'test'}) is None"],
        env=env, cwd=ROOT, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
