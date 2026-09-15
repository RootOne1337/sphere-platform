"""Bounded two-device pilot drill with exact-scope faults and independent cleanup.

Run explicitly: python -m scripts.pilot.network_recovery_probe --pilot-dir PRIVATE
--mode android|server|both|browser. Requires the private pilot/soak configuration.
Android blocks only the second APK UID (IPv4 and IPv6). Server pauses the public
gateway; browser pauses the common Nginx, affecting both web and Android paths.
Only reviewed Android system DAGs execute. Raw evidence stays in the pilot folder.
"""

import argparse
import asyncio
import json
import shlex
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import websockets
from cryptography.hazmat.primitives import serialization

from scripts.discovery_manifest import verify_manifest
from scripts.discovery_publisher import exclusive_lock, verify_route
from scripts.pilot.android_soak import failure_detail, safe_dag, validate_result
from scripts.pilot.atomic_json import write_json

c = SimpleNamespace()


def run(args, **kw):
    return subprocess.check_output(
        args,
        text=True,
        encoding="utf8",
        errors="replace",
        timeout=25,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        **kw,
    ).strip()


def shell(serial, *args):
    return run([c.adb[0], "-s", serial, "shell", shlex.join(args)])


def inspect(cid):
    return json.loads(run(["docker", "inspect", cid]))[0]


def restore(spec):
    errors = []
    for rule in spec["rules"]:
        for tool in rule["tools"]:
            check = shlex.join([tool, "-C", *rule["args"]])
            if shell(rule["serial"], "su", "-c", check + " >/dev/null 2>&1; echo $?") == "0":
                try:
                    shell(rule["serial"], "su", "-c", shlex.join([tool, "-D", *rule["args"]]))
                except Exception as exc:
                    errors.append(type(exc).__name__)
    if spec.get("gateway"):
        value = inspect(spec["gateway"])
        assert value["Config"]["Labels"]["com.docker.compose.project"] == spec["project"]
        if value["State"]["Paused"]:
            try:
                run(["docker", "unpause", value["Id"]])
            except Exception as exc:
                errors.append(type(exc).__name__)
    if errors:
        raise RuntimeError("cleanup_failed:" + ",".join(errors))


if len(sys.argv) > 1 and sys.argv[1] == "--guard":
    path = Path(sys.argv[2])
    spec = json.loads(path.read_text())
    c.adb = [spec["adb"]]
    path.with_suffix(".ready").write_text("guard ready")
    while time.time() < spec["guard_deadline"] and not path.with_suffix(".restore").exists():
        time.sleep(1)
    restore(spec)
    path.with_suffix(".restored").write_text(datetime.now(timezone.utc).isoformat())
    sys.exit(0)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--pilot-dir", type=Path, required=True)
parser.add_argument("--mode", choices=["android", "server", "both", "browser"], required=True)
args = parser.parse_args()
mode = args.mode
c.work = args.pilot_dir.resolve()
c.state = json.loads((c.work / "installation.json").read_text(encoding="utf8"))
assert c.state["project"].startswith(
    "sphere-pilot-"
), "Only an explicitly named isolated pilot is supported"
config = json.loads((c.work / "overnight-config.json").read_text(encoding="utf8"))
devices = config["devices"]
assert len(devices) == 2
assert len({d["id"] for d in devices}) == 2 and len({d["serial"] for d in devices}) == 2
for d in devices:
    uuid.UUID(d["id"])
c.package = config["package"]
assert c.package.startswith("com.sphereplatform.agent.pilot.")
c.adb = [config["adb"]]
c.bootstrap = json.loads((c.work / "remote/signed-bootstrap.json").read_text(encoding="utf8"))
c.public_key = serialization.load_pem_public_key(Path(config["public_key"]).read_bytes())
c.verify_manifest = verify_manifest
c.httpx = httpx


def checked_container(name):
    value = inspect(name)
    assert value["Config"]["Labels"]["com.docker.compose.project"] == c.state["project"]
    return value


c.checked_container = checked_container
out = c.work / "network-recovery" / f"{mode}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
out.mkdir(parents=True, exist_ok=False)
targets = devices[1:] if mode == "android" else devices
current = c.verify_manifest(
    (c.work / "remote/public/agent.signed.json").read_bytes(),
    c.public_key,
    c.bootstrap["key_id"],
    c.bootstrap["installation_id"],
)
gateway = c.checked_container(
    c.state["project"] + ("-nginx-1" if mode == "browser" else "-public-gateway-1")
)
assert not gateway["State"]["Paused"]
backend = c.checked_container(c.state["project"] + "-backend-1")
all_ids = run(["docker", "ps", "-aq"]).split()
protected = [
    {"id": v["Id"], "image": v["Image"], "started": v["State"]["StartedAt"]}
    for v in json.loads(run(["docker", "inspect", *all_ids]))
]
spec = {
    "project": c.state["project"],
    "adb": config["adb"],
    "rules": [],
    "gateway": gateway["Id"] if mode in ("server", "both", "browser") else None,
    "guard_deadline": time.time() + 300,
}
if mode in ("android", "both"):
    d = devices[1]
    uid = shell(d["serial"], "run-as", c.package, "id", "-u")
    assert uid.isdigit() and int(uid) > 10000
    tag = "sphere-fault-" + uuid.uuid4().hex
    rule = {
        "serial": d["serial"],
        "tools": ["iptables", "ip6tables"],
        "args": [
            "OUTPUT",
            "-m",
            "owner",
            "--uid-owner",
            uid,
            "-m",
            "comment",
            "--comment",
            tag,
            "-j",
            "DROP",
        ],
    }
    for tool in rule["tools"]:
        shell(d["serial"], "su", "-c", tool + " -S OUTPUT")
    spec["rules"].append(rule)
path = out / "guard.json"
path.write_text(json.dumps(spec, indent=2))
e = {
    "started": datetime.now(timezone.utc).isoformat(),
    "mode": mode,
    "planned_fault_seconds": 75,
    "devices": {},
    "samples": [],
    "cleanup_verified": False,
    "passed": False,
}


def save():
    write_json(out / "result.json", e)


def live(d):
    code = """import asyncio,json,sys
from backend.database.redis_client import connect_redis,disconnect_redis,get_redis_binary
from backend.services.device_status_cache import DeviceStatusCache
async def main():
 await connect_redis()
 try:
  value=await DeviceStatusCache(await get_redis_binary()).get_status(sys.argv[1])
  print(json.dumps(value.model_dump(mode='json') if value else None))
 finally: await disconnect_redis()
asyncio.run(main())
"""
    return json.loads(
        run(
            ["docker", "exec", "-i", backend["Id"], "python", "-", d["id"]], input=code
        ).splitlines()[-1]
    )


for d in devices:
    pid = shell(d["serial"], "pidof", c.package)
    assert pid.isdigit()
    status = live(d)
    assert status and status.get("ws_session_id")
    logs = run([c.adb[0], "-s", d["serial"], "logcat", "-b", "crash", "-d"])
    (out / (d["serial"] + "-crash-before.log")).write_text(logs, encoding="utf8")
    e["devices"][d["id"]] = {
        "pid_before": pid,
        "session_before": status["ws_session_id"],
        "stream_frames": 0,
        "stream_connections": 0,
        "stream_errors": [],
    }


async def main():
    with c.httpx.Client(base_url="http://127.0.0.1:18080", timeout=20) as api:
        verify_route(api, current["server_url"], c.bootstrap["installation_id"])
        nginx = c.checked_container(c.state["project"] + "-nginx-1")
        assert any(
            p["HostPort"] == "18080"
            for ports in nginx["HostConfig"]["PortBindings"].values()
            for p in (ports or [])
        )
        assert api.get("/api/v1/health/readyz").status_code == 200
        r = api.post(
            "/api/v1/auth/login",
            json=json.loads((c.work / "operator-credentials.json").read_text()),
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        api.headers["Authorization"] = "Bearer " + token
        script = api.get("/api/v1/scripts/" + config["script_id"])
        script.raise_for_status()
        assert script.json()["current_version_id"] == config["version_id"]
        assert script.json()["current_version"]["dag"] == safe_dag()
        for d in targets:
            for status in ("queued", "assigned", "running"):
                r = api.get(
                    "/api/v1/tasks", params={"device_id": d["id"], "status": status, "per_page": 1}
                )
                r.raise_for_status()
                assert r.json()["total"] == 0

        async def watch(d):
            row = e["devices"][d["id"]]
            while True:
                try:
                    async with websockets.connect(
                        "ws://127.0.0.1:18080/ws/stream/" + d["id"],
                        max_size=16 * 1024 * 1024,
                        open_timeout=15,
                    ) as ws:
                        row["stream_connections"] += 1
                        await ws.send(json.dumps({"token": token}))
                        async for value in ws:
                            if isinstance(value, bytes):
                                assert (
                                    value[0] == 1
                                    and int.from_bytes(value[10:14], "big") == len(value) - 14
                                )
                                row["stream_frames"] += 1
                                row["last_frame_at"] = time.time()
                            else:
                                data = json.loads(value)
                                if data.get("type") == "ping":
                                    await ws.send(json.dumps({"type": "pong"}))
                                if data.get("type") == "error":
                                    row["stream_errors"].append(data.get("error"))
                except (OSError, websockets.ConnectionClosed) as exc:
                    row["stream_errors"].append(type(exc).__name__)
                    await asyncio.sleep(1)

        watchers = [asyncio.create_task(watch(d)) for d in devices]
        guard = None
        try:
            async with asyncio.timeout(20):
                while not all(e["devices"][d["id"]]["stream_frames"] for d in devices):
                    await asyncio.sleep(0.2)
            guard = subprocess.Popen(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-m",
                    "scripts.pilot.network_recovery_probe",
                    "--guard",
                    str(path),
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            async with asyncio.timeout(10):
                while not path.with_suffix(".ready").exists():
                    assert guard.poll() is None, "Cleanup guard exited before fault"
                    await asyncio.sleep(0.1)
            try:
                for rule in spec["rules"]:
                    for tool in rule["tools"]:
                        shell(
                            rule["serial"],
                            "su",
                            "-c",
                            shlex.join([tool, "-I", "OUTPUT", "1", *rule["args"][1:]]),
                        )
                if spec["gateway"]:
                    run(["docker", "pause", spec["gateway"]])
                e["fault_started"] = datetime.now(timezone.utc).isoformat()
                save()
                print("FAULT_ACTIVE " + str(out), flush=True)
                fault_start = time.monotonic()
                for i in range(5):
                    await asyncio.sleep(max(0, fault_start + (i + 1) * 15 - time.monotonic()))
                    sample = {
                        "seconds": round(time.monotonic() - fault_start, 3),
                        "sessions": {
                            d["id"]: (await asyncio.to_thread(live, d) or {}).get("ws_session_id")
                            for d in targets
                        },
                    }
                    e["samples"].append(sample)
                    save()
                    print(json.dumps(sample), flush=True)
            finally:
                restore(spec)
                path.with_suffix(".restore").write_text("restore now")
                e["cleanup_verified"] = True
                e["fault_restored"] = datetime.now(timezone.utc).isoformat()
                save()
                print("NETWORK_RESTORED", flush=True)
            recovered = time.monotonic()
            for d in targets:
                row = e["devices"][d["id"]]
                async with asyncio.timeout(150):
                    while True:
                        status = await asyncio.to_thread(live, d)
                        if (
                            status
                            and status.get("ws_session_id")
                            and status["ws_session_id"] != row["session_before"]
                        ):
                            row["session_after"] = status["ws_session_id"]
                            row["reconnect_seconds"] = round(time.monotonic() - recovered, 3)
                            break
                        await asyncio.sleep(1)
                marker = "SPHERE_RECOVERY_" + mode.upper()
                r = await asyncio.to_thread(
                    api.post,
                    "/api/v1/devices/" + d["id"] + "/shell",
                    json={"command": "echo " + marker},
                )
                assert r.status_code == 200 and r.json().get("output", "").strip() == marker, (
                    r.status_code,
                    r.text[:200],
                )
                row["echo_passed"] = True
                frames = row["stream_frames"]
                r = api.post(
                    "/api/v1/tasks",
                    json={"script_id": config["script_id"], "device_id": d["id"], "priority": 5},
                )
                r.raise_for_status()
                row["task_id"] = r.json()["id"]
                save()
                async with asyncio.timeout(45):
                    while True:
                        r = await asyncio.to_thread(api.get, "/api/v1/tasks/" + row["task_id"])
                        r.raise_for_status()
                        task = r.json()
                        if task["status"] == "completed":
                            break
                        assert task["status"] not in ("failed", "cancelled", "timeout"), task[
                            "status"
                        ]
                        await asyncio.sleep(0.3)
                validate_result(task, d["id"], config["version_id"])
                row["dag_passed"] = True
                (out / (d["serial"] + "-task.json")).write_text(
                    json.dumps(task, indent=2), encoding="utf8"
                )
                async with asyncio.timeout(12):
                    while row["stream_frames"] <= frames:
                        await asyncio.sleep(0.1)
                row["stream_resumed_without_viewer_reopen"] = row["stream_connections"] == 1
                row["frames_after_recovery"] = row["stream_frames"] - frames
                row["same_apk_pid"] = shell(d["serial"], "pidof", c.package) == row["pid_before"]
                assert row["same_apk_pid"]
            e["passed"] = True
        finally:
            for w in watchers:
                w.cancel()
            await asyncio.gather(*watchers, return_exceptions=True)
            if guard:
                assert await asyncio.to_thread(guard.wait, 30) == 0
                assert path.with_suffix(".restored").exists()
            for rule in spec["rules"]:
                for tool in rule["tools"]:
                    assert (
                        shell(
                            rule["serial"],
                            "su",
                            "-c",
                            shlex.join([tool, "-C", *rule["args"]]) + " >/dev/null 2>&1; echo $?",
                        )
                        == "1"
                    )
            for d in devices:
                logs = run([c.adb[0], "-s", d["serial"], "logcat", "-b", "crash", "-d"])
                (out / (d["serial"] + "-crash-after.log")).write_text(logs, encoding="utf8")
                e["devices"][d["id"]]["crash_buffer_unchanged"] = logs == (
                    out / (d["serial"] + "-crash-before.log")
                ).read_text(encoding="utf8")
                assert e["devices"][d["id"]]["crash_buffer_unchanged"]
                app_log = run(
                    [
                        c.adb[0],
                        "-s",
                        d["serial"],
                        "logcat",
                        "-d",
                        "--pid=" + e["devices"][d["id"]]["pid_before"],
                        "-t",
                        "2000",
                    ]
                )
                (out / (d["serial"] + "-app.log")).write_text(app_log, encoding="utf8")
            e["containers_preserved"] = all(
                (v := inspect(b["id"]))["Image"] == b["image"]
                and v["State"]["StartedAt"] == b["started"]
                and not v["State"]["Paused"]
                for b in protected
            )
            save()
            assert e["containers_preserved"]


try:
    with exclusive_lock(c.work / "network-recovery" / "active.lock"):
        asyncio.run(main())
except BaseException as exc:
    e["passed"] = False
    e["error"] = failure_detail(exc)
    save()
    raise
print(json.dumps(e, indent=2), flush=True)
