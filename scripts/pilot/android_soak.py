"""Bounded owned-device soak through Sphere HTTPS/batches/WSS, with private evidence.

Run from the repository: python -m scripts.pilot.android_soak --config PRIVATE.json
The runner never installs/launches APKs or modifies Android settings. ADB is
optional, read-only incident evidence; all test actions travel through Sphere.
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import websockets
from cryptography.hazmat.primitives import serialization

from backend.schemas.dag import DAGScript
from backend.schemas.pipeline import PipelineStepSchema
from scripts.discovery_manifest import verify_manifest
from scripts.discovery_publisher import verify_route
from scripts.pilot.summarize_soak import summarize

FIXTURE = Path(__file__).with_name("android-safe-soak.json")
EXPECTED_NODES = [
    "start", "counter", "home", "settle", "expand", "observe", "collapse",
    "increment", "branch", "echo", "verify", "sdk", "end",
]
TERMINAL = {"completed", "failed", "partial", "cancelled", "timeout"}


class SoakFailure(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise SoakFailure(reason)


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def safe_dag():
    dag = json.loads(FIXTURE.read_text(encoding="utf-8"))
    # Reviewed actions only. A fixture edit must not silently broaden night work.
    commands = {"cmd statusbar expand-notifications", "cmd statusbar collapse",
                "echo SPHERE_SAFE_SOAK_OK", "getprop ro.build.version.sdk"}
    for node in dag["nodes"]:
        action = node["action"]
        kind = action["type"]
        require(kind in {"start", "end", "set_variable", "increment_variable",
                         "key_event", "sleep", "shell", "condition", "assert"}, "Unsafe action")
        require(node.get("retry", 0) == 0, "No automatic side-effect retries")
        if kind == "shell":
            require(action["command"] in commands, "Unreviewed shell command")
        if kind == "key_event":
            require(action["keycode"] == 3, "Only HOME key is allowed")
        if kind == "condition":
            require(action["code"] == "return ctx.counter == '1'", "Unreviewed Lua")
        if kind == "sleep":
            require(0 <= action["ms"] <= 2000, "Sleep exceeds fixture budget")
    require(dag["timeout_ms"] == 45000, "DAG timeout changed")
    return DAGScript.model_validate(dag).model_dump()


def validate_result(detail, device, version):
    require(detail["device_id"] == device, "Result device mismatch")
    require(detail["script_version_id"] == version, "Result version mismatch")
    require(detail["status"] == "completed" and detail["finished_at"], "Task did not complete")
    result = detail.get("result") or {}
    require(result.get("success") is True, "APK reported task failure")
    logs = result.get("node_logs", [])
    require([row["node_id"] for row in logs] == EXPECTED_NODES, "Missing/duplicate/out-of-order node receipt")
    require(all(row.get("success") is True for row in logs), "Failed node receipt")
    require(result.get("nodes_executed") == len(EXPECTED_NODES), "Incorrect executed-node count")
    by_id = {row["node_id"]: row for row in logs}
    require(by_id["echo"].get("output", "").strip() == "SPHERE_SAFE_SOAK_OK", "Wrong native echo")
    require(by_id["sdk"].get("output", "").strip().isdigit(), "Missing native SDK result")
    return result


def pipeline_steps(script_id):
    steps = [
        {"id": "hold", "name": "Safe pause boundary", "type": "delay", "params": {"delay_ms": 8000},
         "timeout_ms": 15000, "on_success": "native"},
        {"id": "native", "name": "Reviewed native Android DAG", "type": "execute_script",
         "params": {"script_id": script_id}, "timeout_ms": 60000, "on_success": "finish"},
        {"id": "finish", "name": "Completion boundary", "type": "delay",
         "params": {"delay_ms": 200}, "timeout_ms": 2000},
    ]
    return [PipelineStepSchema.model_validate(step).model_dump() for step in steps]


class Viewer:
    def __init__(self, ws, device):
        self.ws, self.device = ws, device
        self.frames = self.bytes = 0
        self.nals = set()
        self.started = time.monotonic()
        self.first_frame = None
        self.ready = asyncio.Event()
        self.reader = asyncio.create_task(self.receive())

    async def receive(self):
        async for data in self.ws:
            if isinstance(data, bytes):
                require(len(data) > 14 and data[0] == 1, "Invalid frame header")
                require(int.from_bytes(data[10:14], "big") == len(data) - 14, "Truncated frame")
                payload = data[14:]
                offset = 4 if payload.startswith(b"\0\0\0\1") else 3 if payload.startswith(b"\0\0\1") else 0
                require(len(payload) > offset, "Empty NAL")
                self.nals.add(payload[offset] & 31)
                self.frames += 1
                self.bytes += len(data)
                if self.first_frame is None:
                    self.first_frame = round(time.monotonic() - self.started, 3)
                if {5, 7, 8} <= self.nals:
                    self.ready.set()
            else:
                message = json.loads(data)
                require(message.get("type") != "error", "Viewer server error")
                if message.get("type") == "ping":
                    await self.ws.send(json.dumps({"type": "pong"}))
        raise SoakFailure("Viewer closed before requested disconnect")

    def check(self):
        if self.reader.done():
            self.reader.result()

    def summary(self):
        return {"device": self.device, "frames": self.frames, "bytes": self.bytes,
                "nal_types": sorted(self.nals), "first_frame_seconds": self.first_frame}

    async def stop(self):
        self.reader.cancel()
        await asyncio.gather(self.reader, return_exceptions=True)


class Runner:
    def __init__(self, config, out, seconds):
        self.config, self.out, self.seconds = config, out, seconds
        self.devices = config["devices"]
        require(1 <= len(self.devices) <= 8, "Explicit bounded device set required")
        require(len({d['id'] for d in self.devices}) == len(self.devices), "Duplicate device")
        for device in self.devices:
            uuid.UUID(device["id"])
        self.package = config["package"]
        require(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_.]+", self.package), "Invalid package")
        self.dag = safe_dag()
        self.pids = {}
        self.api = None
        self.token = self.base = None
        self.auth_at = 0.0
        self.active_batch = None
        self.active_pipelines = []
        self.state = {"run_id": out.name, "status": "starting", "started_at": utc(),
                      "planned_seconds": seconds, "pid": os.getpid(), "cycles_passed": 0,
                      "tasks_passed": 0, "commands_passed": 0, "samples": 0,
                      "pipeline_controls_passed": 0,
                      "devices": [d["id"] for d in self.devices], "script_id": config["script_id"],
                      "script_version_id": config["version_id"], "failure": None,
                      "expected_end": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}

    def event(self, kind, **values):
        row = {"at": utc(), "event": kind, **values}
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.state["updated_at"] = row["at"]
        write_json(self.out / "status.json", self.state)

    def stopping(self):
        return (self.out / "STOP").exists()

    def resolve_route(self):
        key = serialization.load_pem_public_key(Path(self.config["public_key"]).read_bytes())
        manifest = verify_manifest(Path(self.config["signed_manifest"]).read_bytes(), key,
                                   self.config["key_id"], self.config["installation_id"])
        require(manifest["config_version"] >= self.config["minimum_config_version"], "Discovery rollback")
        base = manifest["server_url"]
        with httpx.Client(timeout=20) as probe:
            verify_route(probe, base, self.config["installation_id"])
        return base

    async def authenticate(self):
        base = await asyncio.to_thread(self.resolve_route)
        if self.api:
            await self.api.aclose()
        self.api = httpx.AsyncClient(base_url=base, timeout=35)
        response = await self.api.post("/api/v1/auth/login", json=json.loads(
            Path(self.config["credentials"]).read_text(encoding="utf-8")))
        require(response.status_code == 200, f"Login HTTP {response.status_code}")
        self.token = response.json()["access_token"]
        self.api.headers["Authorization"] = "Bearer " + self.token
        self.base, self.auth_at = base, time.monotonic()
        self.event("route_authenticated")

    async def request(self, method, path, **kwargs):
        # No automatic mutation retries: a lost POST response can mean committed.
        response = await self.api.request(method, path, **kwargs)
        require(response.is_success, f"{method} {path} HTTP {response.status_code}")
        return response.json() if response.content else None

    async def shell(self, device, command):
        started = time.monotonic()
        data = await self.request("POST", f"/api/v1/devices/{device}/shell", json={"command": command})
        require("error" not in data and isinstance(data.get("output"), str), "Native shell failed")
        self.state["commands_passed"] += 1
        self.event("command", device=device, command=command, seconds=round(time.monotonic()-started, 3))
        return data["output"]

    async def check_script(self):
        script = await self.request("GET", f"/api/v1/scripts/{self.config['script_id']}")
        require(script["current_version_id"] == self.config["version_id"], "Pinned script version changed")
        require(script["current_version"]["dag"] == self.dag, "Server DAG differs from reviewed fixture")

    async def sample(self, phase, memory=False):
        for device in self.devices:
            did = device["id"]
            pid = (await self.shell(did, "pidof " + self.package)).strip()
            require(pid.isdigit(), "APK process absent")
            if did in self.pids:
                require(pid == self.pids[did], "APK process restarted")
            self.pids[did] = pid
            listed = await self.request("GET", f"/api/v1/devices/{did}")
            require(listed["status"] == "online", "Device API reported offline")
            marker = "SPHERE_SOAK_" + str(self.state["cycles_passed"])
            require((await self.shell(did, "echo " + marker)).strip() == marker, "Health echo mismatch")
            row = {"device": did, "phase": phase, "apk_pid": pid, "online": True}
            if memory:
                raw = await self.shell(did, "dumpsys meminfo " + self.package)
                filename = f"memory-{self.state['cycles_passed']:04}-{did}-{phase}.txt"
                (self.out / filename).write_text(raw, encoding="utf-8")
                match = re.search(r"TOTAL(?: PSS)?:\s+(\d+)", raw)
                require(match is not None, "Memory observation missing")
                row["pss_kib"] = int(match.group(1))
                require(row["pss_kib"] < 350_000, "APK memory exceeds 350 MB test stop budget")
                stat = await self.shell(did, "cat /proc/" + pid + "/stat")
                fields = stat.rpartition(")")[2].split()
                require(len(fields) >= 13, "CPU observation missing")
                row["cpu_user_ticks"], row["cpu_system_ticks"] = int(fields[11]), int(fields[12])
                projection = await self.shell(did, "dumpsys media_projection")
                row["projection_active"] = self.package in projection
                if phase == "stream":
                    require(row["projection_active"], "No active native projection while viewing")
            self.state["samples"] += 1
            self.event("sample", **row)

    async def no_existing_tasks(self):
        for device in self.devices:
            for status in ["queued", "assigned", "running"]:
                listing = await self.request("GET", "/api/v1/tasks",
                    params={"device_id": device["id"], "status": status, "per_page": 1})
                require(listing["total"] == 0, "Existing active task; do not overlap owner work")

    async def pipeline_controls(self):
        pipeline_id = self.config["pipeline_id"]
        pipeline = await self.request("GET", f"/api/v1/pipelines/{pipeline_id}")
        require(pipeline["steps"] == pipeline_steps(self.config["script_id"]), "Pipeline fixture changed")
        require(pipeline["global_timeout_ms"] == 90000 and pipeline["max_retries"] == 0,
                "Pipeline bounds changed")
        await self.no_existing_tasks()

        async def read(run_id):
            return await self.request("GET", f"/api/v1/pipelines/runs/{run_id}")

        async def until(run_id, predicate, seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                row = await read(run_id)
                if predicate(row):
                    return row
                require(row["status"] not in {"failed", "timed_out", "cancelled"}, "Pipeline failed")
                await asyncio.sleep(0.5)
            raise SoakFailure("Pipeline boundary timed out")

        for index, device in enumerate(self.devices):
            if self.stopping():
                return
            run = await self.request("POST", f"/api/v1/pipelines/{pipeline_id}/run",
                                     json={"device_id": device["id"]})
            run_id = run["id"]
            self.active_pipelines.append(run_id)
            self.event("pipeline_admitted", run_id=run_id, device=device["id"])
            await until(run_id, lambda r: r["status"] == "running" and r["current_step_id"] == "hold", 20)
            action = "pause" if index % 2 == 0 else "cancel"
            response = await self.request("POST", f"/api/v1/pipelines/runs/{run_id}/{action}")
            require(response["status"] == ("paused" if action == "pause" else "cancelled"), "Control not accepted")
            await asyncio.sleep(10)
            held = await read(run_id)
            require(held["status"] == response["status"] and held["current_task_id"] is None,
                    "Pipeline control admitted Android task")
            require([s["step_id"] for s in held["step_logs"]] == ["hold"], "Pipeline crossed held boundary")
            if action == "pause":
                await self.request("POST", f"/api/v1/pipelines/runs/{run_id}/resume")
                done = await until(run_id, lambda r: r["status"] == "completed", 70)
                require([s["step_id"] for s in done["step_logs"]] == ["hold", "native", "finish"],
                        "Resume duplicated/omitted steps")
                require(all(s["status"] == "success" for s in done["step_logs"]), "Pipeline step failed")
                task_id = done["context"].get("last_task_id")
                require(task_id is not None, "Pipeline native task ID missing")
                detail = await self.request("GET", f"/api/v1/tasks/{task_id}")
                validate_result(detail, device["id"], self.config["version_id"])
            else:
                done = held
            write_json(self.out / f"pipeline-{run_id}.json", {
                "run_id": run_id, "device_id": device["id"], "action": action,
                "native_task_id": done.get("context", {}).get("last_task_id"),
                "held_status": held["status"], "status": done["status"], "step_logs": done["step_logs"]})
            self.active_pipelines.remove(run_id)
            self.state["pipeline_controls_passed"] += 1
            self.event("pipeline_control_verified", run_id=run_id, device=device["id"], action=action)

    async def batch(self, cycle):
        await self.no_existing_tasks()
        row = await self.request("POST", "/api/v1/batches", json={
            "script_id": self.config["script_id"], "device_ids": self.state["devices"],
            "wave_size": 1 if cycle % 2 else len(self.devices), "wave_delay_ms": 1000,
            "jitter_ms": 200, "priority": 5, "stagger_by_workstation": False,
            "name": f"{self.out.name} cycle {cycle}",
        })
        self.active_batch = row["id"]
        self.state["active_batch"] = self.active_batch
        self.event("batch_admitted", batch_id=self.active_batch, cycle=cycle)
        started = time.monotonic()
        while time.monotonic() - started < 90:
            row = await self.request("GET", f"/api/v1/batches/{self.active_batch}")
            if row["status"] in TERMINAL:
                break
            await asyncio.sleep(2)
        require(row["status"] == "completed" and row["succeeded"] == len(self.devices)
                and row["failed"] == 0, "Batch failed or timed out")
        listing = await self.request("GET", "/api/v1/tasks", params={"batch_id": self.active_batch})
        require(listing["total"] == len(self.devices), "Unexpected task cardinality")
        require({t["device_id"] for t in listing["items"]} == set(self.state["devices"]), "Task device mismatch")
        for task in listing["items"]:
            detail = await self.request("GET", f"/api/v1/tasks/{task['id']}")
            result = validate_result(detail, task["device_id"], self.config["version_id"])
            write_json(self.out / f"task-{task['id']}.json", {
                "task_id": task["id"], "batch_id": self.active_batch, "device_id": task["device_id"],
                "script_version_id": detail["script_version_id"], "status": detail["status"],
                "started_at": detail["started_at"], "finished_at": detail["finished_at"], "result": result})
            self.state["tasks_passed"] += 1
            self.event("task_verified", task_id=task["id"], device=task["device_id"], nodes=len(EXPECTED_NODES))
        self.event("batch_verified", batch_id=self.active_batch, seconds=round(time.monotonic()-started, 3))
        self.active_batch = None
        self.state["active_batch"] = None

    async def open_viewer(self, stack, device):
        ws_url = self.base.replace("https://", "wss://") + f"/ws/stream/{device}"
        ws = await stack.enter_async_context(websockets.connect(ws_url, open_timeout=20,
                                            close_timeout=5, max_size=16*1024*1024, max_queue=4))
        await ws.send(json.dumps({"token": self.token}))
        viewer = Viewer(ws, device)
        stack.push_async_callback(viewer.stop)
        async with asyncio.timeout(20):
            while not viewer.ready.is_set():
                viewer.check()
                await asyncio.sleep(0.1)
        return viewer

    async def cycle(self, number):
        started = time.monotonic()
        require(shutil.disk_usage(self.out).free > 1_000_000_000, "Less than 1 GB evidence disk free")
        if started - self.auth_at > 1200:
            await self.authenticate()
        await self.check_script()
        viewers = []
        async with AsyncExitStack() as stack:
            for device in self.devices:
                viewers.append(await self.open_viewer(stack, device["id"]))
            frames_before = [v.frames for v in viewers]
            await self.batch(number)
            if self.config.get("pipeline_id") and (number == 1 or number % 10 == 0):
                await self.pipeline_controls()
            await asyncio.sleep(1)
            for viewer, before in zip(viewers, frames_before):
                viewer.check()
                require(viewer.frames > before, "No new frames during native UI exercise")
            await self.sample("stream", memory=True)
            if number % 4 == 0:
                async with AsyncExitStack() as overlap:
                    for device in self.devices:
                        extra = await self.open_viewer(overlap, device["id"])
                        self.event("overlap_verified", **extra.summary())
            while time.monotonic() - started < 75 and not self.stopping():
                for viewer in viewers:
                    viewer.check()
                self.event("stream_observation", cycle=number,
                           viewers=[v.summary() for v in viewers])
                for _ in range(10):
                    if self.stopping():
                        break
                    await asyncio.sleep(1)
            for viewer in viewers:
                viewer.check()
                self.event("viewer_verified", **viewer.summary())
        # Closing only our sockets permits the normal last-viewer release path.
        # Do not issue global stream/stop: an operator may still be watching.
        await asyncio.sleep(5)
        await self.sample("after_viewer_close", memory=True)
        self.state["cycles_passed"] += 1
        self.event("cycle_passed", cycle=number)
        while time.monotonic() - started < 120 and not self.stopping():
            await asyncio.sleep(1)

    async def diagnostics(self):
        # No ADB mutation or log clearing. Works even if the APK cannot answer.
        if not self.config.get("adb"):
            return
        for device in self.devices:
            if not device.get("serial"):
                continue
            for label, args in {
                "crash": ["logcat", "-b", "crash", "-d", "-t", "200"],
                "process": ["shell", "pidof", self.package],
                "projection": ["shell", "dumpsys", "media_projection"],
            }.items():
                try:
                    result = await asyncio.to_thread(subprocess.run,
                        [self.config["adb"], "-s", device["serial"], *args],
                        capture_output=True, timeout=20, text=True, encoding="utf-8", errors="replace",
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                    (self.out / f"diagnostic-{device['id']}-{label}.txt").write_text(
                        (result.stdout + result.stderr)[-65536:], encoding="utf-8")
                except Exception as exc:
                    self.event("diagnostic_unavailable", device=device["id"], error_type=type(exc).__name__)

    async def run(self):
        started = time.monotonic()
        try:
            await self.authenticate()
            await self.check_script()
            await self.no_existing_tasks()
            await self.sample("baseline", memory=True)
            self.state["status"] = "running"
            self.event("started", fixture_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest())
            while time.monotonic() - started < self.seconds and not self.stopping():
                await self.cycle(self.state["cycles_passed"] + 1)
            self.state["status"] = "stopped" if self.stopping() else "completed"
        except Exception as exc:
            self.state["status"] = "failed"
            # Never record arbitrary HTTP exception text containing private URLs/tokens.
            self.state["failure"] = str(exc) if isinstance(exc, SoakFailure) else type(exc).__name__
            self.event("failed", reason=self.state["failure"])
        finally:
            for run_id in self.active_pipelines:
                try:
                    await self.request("POST", f"/api/v1/pipelines/runs/{run_id}/cancel")
                except Exception as exc:
                    self.event("pipeline_cleanup_unknown", run_id=run_id, error_type=type(exc).__name__)
            if self.active_batch and self.api:
                try:
                    await self.request("DELETE", f"/api/v1/batches/{self.active_batch}")
                    self.event("pending_batch_cancelled", batch_id=self.active_batch)
                except Exception as exc:
                    self.event("batch_cleanup_unknown", error_type=type(exc).__name__)
            # Current tasks are bounded to 45 seconds. Do not kill other tasks/apps.
            await self.diagnostics()
            if self.api:
                await self.api.aclose()
            self.state["finished_at"] = utc()
            self.state["elapsed_seconds"] = round(time.monotonic() - started, 3)
            self.event("finished", status=self.state["status"])
            write_json(self.out / "summary.json", summarize(self.out))
        return 0 if self.state["status"] in {"completed", "stopped"} else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=8*3600)
    args = parser.parse_args()
    require(120 <= args.seconds <= 12*3600, "Duration must be 120 seconds to 12 hours")
    args.output.mkdir(parents=True, exist_ok=False)
    runner = Runner(json.loads(args.config.read_text(encoding="utf-8")), args.output, args.seconds)
    lock = args.config.resolve().with_suffix(".lock")
    # A stale lock after an OS/process crash needs inspection, not silent takeover.
    with lock.open("x", encoding="utf-8") as handle:
        json.dump({"pid": os.getpid(), "output": str(args.output.resolve()), "started_at": utc()}, handle)
    # Scoped to this process; no persistent power-plan or display-setting mutation.
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        return asyncio.run(runner.run())
    finally:
        if os.name == "nt":
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        lock.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
