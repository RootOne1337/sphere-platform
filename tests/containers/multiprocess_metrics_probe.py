"""Run inside the disposable Linux container against four real HTTP workers."""
import argparse
import json
import os
import signal
import subprocess
import time
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--recycles", type=int, default=16)
args = parser.parse_args()
assert 0 <= args.recycles <= 512
BASE = "http://127.0.0.1:8000"


def read(path, *, raw=False, base=BASE):
    request = urllib.request.Request(base + path, headers={"Connection": "close"})
    with urllib.request.urlopen(request, timeout=3) as response:
        body = response.read().decode()
    return body if raw else json.loads(body)


def wait_workers():
    workers = set()
    directory = None
    deadline = time.monotonic() + 20
    while len(workers) < 4:
        assert time.monotonic() < deadline, "Did not reach all four HTTP workers"
        try:
            receipt = read("/identity")
            workers.add(receipt["pid"])
            directory = receipt["directory"]
        except OSError:
            time.sleep(0.1)
    return workers, directory


def scrape():
    samples = {}
    body = read("/metrics", raw=True)
    for family in text_string_to_metric_families(body):
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            assert key not in samples, f"Duplicate metric sample: {key}"
            samples[key] = sample.value
    return samples


def value(samples, name, **labels):
    return samples.get((name, tuple(sorted(labels.items()))), 0)


workers, directory = wait_workers()
assert len(workers) == 4
before = scrape()
assert value(before, "sphere_metrics_worker_processes") == 4
assert value(before, "sphere_db_pool_size") == 40
assert value(before, "sphere_db_pool_checked_out") == 4
labels = {"method": "GET", "endpoint": "/canary/{id}", "status_code": "200"}
assert value(before, "sphere_http_requests_total", **labels) == 0, "Master reused old counters"
# Bind a keepalive connection to each worker. Sequential new connections are
# not fairly distributed by the kernel; counting 128 in one process is no proof
# that this endpoint aggregates requests from four independent workers.
connections = {}
deadline = time.monotonic() + 20
while len(connections) < 4:
    assert time.monotonic() < deadline, "Could not bind all four worker connections"
    connection = HTTPConnection("127.0.0.1", 8000, timeout=3)
    connection.request("GET", "/identity")
    response = connection.getresponse()
    pid = json.loads(response.read())["pid"]
    if pid in connections:
        connection.close()
    else:
        connections[pid] = connection
assert set(connections) == workers
for index in range(32):
    for pid, connection in connections.items():
        connection.request("GET", f"/canary/item-{index}")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["pid"] == pid
for connection in connections.values():
    connection.close()
after = scrape()
assert value(after, "sphere_http_requests_total", **labels) == 128
assert value(after, "sphere_http_request_duration_seconds_count", method="GET", endpoint="/canary/{id}") == 128

# The Gunicorn master must retire the actual dead child's live gauges.
retired = next(iter(workers))
os.kill(retired, signal.SIGTERM)
deadline = time.monotonic() + 20
replacement = None
while time.monotonic() < deadline:
    receipt = read("/identity")
    if receipt["pid"] not in workers:
        replacement = receipt["pid"]
    after = scrape()
    retired_gauge = list(Path(directory).glob(f"gauge_live*_{retired}.db"))
    if replacement and not retired_gauge and value(after, "sphere_metrics_worker_processes") == 4:
        break
    time.sleep(0.1)
else:
    raise AssertionError("Gunicorn did not replace/retire the worker")
assert value(after, "sphere_db_pool_size") == 40
assert value(after, "sphere_db_pool_checked_out") == 4
assert value(after, "sphere_http_requests_total", **labels) == 128
assert (Path(directory) / f"counter_{retired}.db").exists()
for index in range(32):
    read(f"/canary/replacement-{index}")
after = scrape()
assert value(after, "sphere_http_requests_total", **labels) == 160


def storage():
    files = list(Path(directory).glob("*.db"))
    return {"files": len(files), "allocated_bytes": sum(path.stat().st_size for path in files)}


initial_storage = storage()
current_workers = (workers - {retired}) | {replacement}
latencies = []
expected = 160
for cycle in range(args.recycles):
    retired_pid = min(current_workers)
    os.kill(retired_pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        receipt = read("/identity")
        new_pid = receipt["pid"]
        if new_pid not in current_workers and not list(Path(directory).glob(f"gauge_live*_{retired_pid}.db")):
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"Worker replacement failed in recycle {cycle}")
    current_workers = (current_workers - {retired_pid}) | {new_pid}
    read(f"/canary/recycle-{cycle}")
    expected += 1
    started = time.perf_counter()
    after = scrape()
    latencies.append((time.perf_counter() - started) * 1000)
    assert value(after, "sphere_metrics_worker_processes") == 4
    assert value(after, "sphere_db_pool_size") == 40
    assert value(after, "sphere_http_requests_total", **labels) == expected
    assert value(after, "sphere_http_request_duration_seconds_count", method="GET", endpoint="/canary/{id}") == expected
final_storage = storage()
# Explicit finite workload budgets, not a claim about unbounded master uptime.
assert final_storage["files"] <= initial_storage["files"] + args.recycles * 2
assert final_storage["allocated_bytes"] <= initial_storage["allocated_bytes"] + args.recycles * 256 * 1024
assert not latencies or max(latencies) < 2000, "Scrape exceeded the 2s canary budget"

# A container restart clears tmpfs even without a hook. Exercise master shutdown
# while this container AND its first master remain alive, so cleanup is proven.
root = Path("/tmp/sphere-metrics")
assert Path(directory).parent == root
assert list(root.glob("master.*")) == [Path(directory)], "Registry survived a container restart"
sentinel = root / "operator-data"
sentinel.mkdir(exist_ok=True)
(sentinel / "keep").write_text("not-owned-by-master")


def secondary_master(*, abrupt):
    process = subprocess.Popen(
        ["/bin/sh", "/app/backend/docker-entrypoint.sh", "gunicorn", "metrics_canary_app:app",
         "--config", "backend/gunicorn_conf.py", "--worker-class", "uvicorn.workers.UvicornWorker",
         "--workers", "2", "--bind", "127.0.0.1:8001", "--graceful-timeout", "5"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            assert process.poll() is None, "Secondary master exited before startup"
            try:
                identity = read("/identity", base="http://127.0.0.1:8001")
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise AssertionError("Secondary master did not start")
        owned = Path(identity["directory"])
        assert owned.parent == root and owned != Path(directory)
        assert (owned / ".owner").read_text().strip() == str(process.pid)
        assert read("/canary/shutdown", base="http://127.0.0.1:8001")
        if abrupt:
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.terminate()
        code = process.wait(timeout=15)
        assert code == (-signal.SIGKILL if abrupt else 0)
        assert owned.exists() == abrupt
        assert Path(directory).is_dir(), "Shutdown deleted the other active master"
        assert (sentinel / "keep").read_text() == "not-owned-by-master"
        return True
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


graceful_cleanup = secondary_master(abrupt=False)
sigkill_residual = secondary_master(abrupt=True)
print(json.dumps({"workers": sorted(workers), "retired_pid": retired, "replacement_pid": replacement,
    "directory": directory, "known_requests": expected, "count_after_worker_exit": 128,
    "db_pool_size": 40, "checked_out": 4, "live_workers": 4, "duplicate_samples": False,
    "master_started_with_zero": True, "worker_recycles": args.recycles,
    "storage_before_recycling": initial_storage, "storage_after_recycling": final_storage,
    "scrape_max_ms": max(latencies, default=0), "graceful_master_cleanup": graceful_cleanup,
    "sigkill_residual_until_container_stop": sigkill_residual,
    "adjacent_operator_data_preserved": True, "concurrent_master_preserved": True}))
