"""Pressure-test the rendered Redis budget in a disposable network-none container.

No installed stack, host port, bind mount or existing volume is used. Run after
installing backend test dependencies (pytest is used by the Compose renderer).
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deployment.test_redis_memory_budget import render_redis  # noqa: E402

FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}


def docker(*args, timeout=60):
    return subprocess.check_output(["docker", *args], text=True, encoding="utf-8",
                                   stderr=subprocess.PIPE, timeout=timeout, **FLAGS).strip()


def info(container, section):
    value = docker("exec", container, "redis-cli", "--raw", "INFO", section)
    return dict(line.split(":", 1) for line in value.splitlines() if ":" in line and not line.startswith("#"))


def wait_ready(container):
    until = time.monotonic() + 30
    while time.monotonic() < until:
        state = json.loads(docker("inspect", container))[0]["State"]
        assert state["Running"], state
        try:
            if docker("exec", container, "redis-cli", "PING", timeout=5) == "PONG":
                return
        except subprocess.CalledProcessError:
            pass
        time.sleep(0.2)
    raise AssertionError("Redis readiness deadline exceeded")


def benchmark(container, requests, output):
    # redis-benchmark does not read REDISCLI_AUTH; this is the synthetic fixture,
    # never an installation credential.
    return subprocess.Popen(["docker", "exec", container, "redis-benchmark", "-a", "fixture", "-t", "set",
                             "-r", "1000000", "-n", str(requests), "-d", "65536", "-c", "4", "-q"],
                            stdout=output, stderr=subprocess.STDOUT, **FLAGS)


def persistence_idle(container):
    until = time.monotonic() + 60
    while time.monotonic() < until:
        value = info(container, "persistence")
        if all(value[key] == "0" for key in ("rdb_bgsave_in_progress", "aof_rewrite_in_progress", "aof_rewrite_scheduled")):
            return value
        time.sleep(0.2)
    raise AssertionError("Persistence did not finish within 60s")


def cgroup_peak(container):
    # Docker Desktop kernels may expose neither v2 memory.peak nor the v1 file.
    # Lack of telemetry is not a measured zero or a reason to skip persistence.
    for path in ("/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory/memory.max_usage_in_bytes"):
        try:
            return {"bytes": int(docker("exec", container, "cat", path)), "source": path}
        except subprocess.CalledProcessError:
            pass
    return {"bytes": None, "source": "unavailable on this kernel"}


def exercise(output):
    output.mkdir(parents=True, exist_ok=False)
    record = {"passed": False, "network": "none", "published_ports": [], "removed": False}
    run_id = "sphere-redis-budget-" + uuid.uuid4().hex[:12]
    container = None
    worker = None
    try:
        with tempfile.TemporaryDirectory() as directory:
            service = render_redis(Path(directory), "pilot")
        memory = str(service["deploy"]["resources"]["limits"]["memory"])
        container = docker("run", "-d", "--name", run_id, "--label", "sphere.audit.redis-budget=" + run_id,
                           "--network", "none", "--memory", memory, "--memory-swap", memory,
                           "-e", "REDISCLI_AUTH=" + service["environment"]["REDIS_PASSWORD"],
                           service["image"], *service["command"])
        configured = json.loads(docker("inspect", container))[0]
        record.update(image_id=configured["Image"], container_bytes=configured["HostConfig"]["Memory"],
                      swap_bytes=configured["HostConfig"]["MemorySwap"])
        wait_ready(container)
        record["initial"] = info(container, "memory")
        with (output / "fill.log").open("w", encoding="utf-8") as log:
            # 875 MiB of writes > the existing 512 MiB dataset cap; bounded process deadline.
            worker = benchmark(container, 14000, log)
            code = worker.wait(timeout=120)
        record["fill_exit"] = code
        assert code == 0, "Redis could not survive bounded SET pressure"
        record["after_fill"] = {**info(container, "memory"), **info(container, "stats")}
        assert int(record["after_fill"]["evicted_keys"]) > 0, "Pressure must reach the actual eviction limit"
        record["persistence"] = []
        for operation in ("BGREWRITEAOF", "BGSAVE"):
            persistence_idle(container)
            with (output / (operation.lower() + ".log")).open("w", encoding="utf-8") as log:
                worker = benchmark(container, 14000, log)
                response = docker("exec", container, "redis-cli", operation)
                assert response.startswith("Background"), response
                assert worker.wait(timeout=120) == 0, "Redis failed during concurrent persistence and writes"
            completed = persistence_idle(container)
            assert completed["rdb_last_bgsave_status"] == "ok"
            assert completed["aof_last_bgrewrite_status"] == "ok"
            assert completed["aof_last_write_status"] == "ok"
            record["persistence"].append({"operation": operation, "response": response, "final": completed})
        record["final_memory"] = info(container, "memory")
        record["cgroup_peak"] = cgroup_peak(container)
        marker = uuid.uuid4().hex
        assert docker("exec", container, "redis-cli", "SET", "audit:restart-marker", marker) == "OK"
        keys = int(docker("exec", container, "redis-cli", "DBSIZE"))
        docker("stop", "--time", "30", container)
        stopped = json.loads(docker("inspect", container))[0]["State"]
        assert stopped["ExitCode"] == 0 and not stopped["OOMKilled"], stopped
        docker("start", container)
        wait_ready(container)
        assert docker("exec", container, "redis-cli", "GET", "audit:restart-marker") == marker
        assert int(docker("exec", container, "redis-cli", "DBSIZE")) == keys
        record.update(passed=True, persisted_key_count=keys, marker_survived_restart=True)
    finally:
        if worker and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)
        if container:
            actual = json.loads(docker("inspect", container))[0]
            assert actual["Config"]["Labels"].get("sphere.audit.redis-budget") == run_id
            record["final_state"] = {k: actual["State"][k] for k in ("Status", "ExitCode", "OOMKilled")}
            record["restart_count"] = actual["RestartCount"]
            (output / "redis.log").write_text(docker("logs", container), encoding="utf-8")
            docker("rm", "-f", "-v", container)
            record["removed"] = True
        (output / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(json.dumps({key: record[key] for key in ("passed", "removed", "final_state") if key in record}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    exercise(parser.parse_args().evidence_dir)
