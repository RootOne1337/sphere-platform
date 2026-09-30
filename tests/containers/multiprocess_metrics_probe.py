"""Run inside the disposable Linux container against four real HTTP workers."""
import json
import os
import signal
import time
import urllib.request
from http.client import HTTPConnection
from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

BASE = "http://127.0.0.1:8000"


def read(path, *, raw=False):
    request = urllib.request.Request(BASE + path, headers={"Connection": "close"})
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
print(json.dumps({"workers": sorted(workers), "retired_pid": retired, "replacement_pid": replacement,
    "directory": directory, "known_requests": 160, "count_after_worker_exit": 128,
    "db_pool_size": 40, "checked_out": 4, "live_workers": 4, "duplicate_samples": False,
    "master_started_with_zero": True}))
