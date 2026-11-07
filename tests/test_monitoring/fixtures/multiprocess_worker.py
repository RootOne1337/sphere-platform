"""Isolated OS-process fixture; env is supplied before any client import."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from backend import metrics
from backend.monitoring.resource_exposition import handle_metrics
from backend.websocket.continuous_observability import OUTCOMES, STAGES

root = Path(sys.argv[1])
index = int(sys.argv[2])
requests = index + 1
metrics.db_pool_size.set(10)
metrics.db_pool_checked_out.set(requests)
for _ in range(requests):
    metrics.http_requests_total.labels("GET", "/canary/{id}", "200").inc()
    metrics.http_request_duration_seconds.labels("GET", "/canary/{id}").observe(0.2)
    for stage in STAGES:
        for outcome in OUTCOMES:
            metrics.continuous_stage_duration_seconds.labels(stage, outcome).observe(0.125)

# Thousands of transient device IDs must not enter mmap keys or new files.
for device in range(1000):
    identity = f"worker-{index}-device-{device}"
    metrics.stream_fps.labels(device_id=identity).set(30)
    metrics.stream_backend_ingress_frames_total.labels(device_id=identity).inc()
    metrics.stream_backend_ingress_packets_by_nal_total.labels(identity, "idr").inc()
    metrics.cleanup_stream_metrics(identity)
metrics.stream_active_viewers.labels(device_id="viewer-device").inc(requests)

(root / f"ready-{index}.json").write_text(json.dumps({"pid": os.getpid()}))
deadline = time.monotonic() + 35
while not (root / f"stop-{index}").exists():
    if time.monotonic() > deadline:
        raise TimeoutError("Parent did not retire test worker")
    if (root / f"scrape-{index}").exists():
        receipt = root / f"metrics-{index}.txt"
        temporary = receipt.with_suffix(".tmp")
        temporary.write_text(handle_metrics(None).body.decode())
        temporary.replace(receipt)
        (root / f"scrape-{index}").unlink()
    time.sleep(0.02)
