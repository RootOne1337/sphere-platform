"""One bounded Windows station check; schedule once per minute under the LDPlayer user.

Only allowlisted, running LDPlayer instances with missing NAT are repair candidates.
No server credential, Internet probe, emulator restart or APK data mutation.
"""
from __future__ import annotations

import argparse
import json
import math
import ntpath
import os
import subprocess
import tempfile
import time
from pathlib import Path

from scripts.ldplayer_network import (
    NetworkRecoveryError,
    RecoveryBusy,
    WindowsHost,
    exclusive_lock,
    owned_processes,
    recover,
    validate_vm,
)

MIN_OBSERVATION_SECONDS = 30
MAX_OBSERVATION_SECONDS = 180
REPAIR_COOLDOWN_SECONDS = 300
MAX_REPAIRS_PER_CYCLE = 1
ERRORS = (NetworkRecoveryError, ValueError, OSError, subprocess.TimeoutExpired)


def write_state(path: Path, state: dict) -> None:
    """Write-ahead cooldown survives process death; readers never see partial JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def validate_config(config: dict) -> dict:
    if not isinstance(config, dict) or set(config) != {"indices", "vboxmanage", "state_path"}:
        raise ValueError("Expected indices, vboxmanage and state_path only")
    indices = config["indices"]
    if (not isinstance(indices, list) or not 1 <= len(indices) <= 256
            or any(not isinstance(i, int) or isinstance(i, bool) or not 0 <= i <= 4095 for i in indices)
            or len(set(indices)) != len(indices)):
        raise ValueError("Expected 1..256 unique LDPlayer indices in 0..4095")
    for key in ("vboxmanage", "state_path"):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise ValueError("Configuration paths must be absolute")
    if Path(config["state_path"]).suffix != ".json":
        raise ValueError("State must use a dedicated JSON file")
    return config


def load_state(path: Path, scope: dict) -> dict:
    if not path.exists():
        return {"version": 1, "scope": scope, "instances": {}, "events": []}
    if path.stat().st_size > 256_000:
        raise ValueError("Watchdog state exceeds size limit")
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state, dict) or state.get("version") != 1 or state.get("scope") != scope
            or not isinstance(state.get("instances"), dict) or not isinstance(state.get("events"), list)):
        raise ValueError("Invalid or differently scoped watchdog state; no repair attempted")
    for key, entry in state["instances"].items():
        if key not in {str(i) for i in scope["indices"]} or not isinstance(entry, dict):
            raise ValueError("Invalid instance state")
        for field in ("missing_since", "last_observed", "last_attempt"):
            value = entry.get(field)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("Invalid watchdog timestamp")
    state["events"] = state["events"][-50:]
    return state


def run_cycle(host, indices: list[int], path: Path, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if not math.isfinite(now) or now < 0:
        raise ValueError("Invalid clock")
    scope = {"directory": ntpath.normcase(host.directory), "indices": sorted(indices)}
    with exclusive_lock(path.with_suffix(".lock")):
        state = load_state(path, scope)
        state.update(checked_at=now, status="ok", internet_verified=False, apk_connection_verified=False)
        try:
            running = host.running_vms()
            processes = host.processes()  # One CIM query for the entire healthy station.
        except ERRORS as exc:
            for entry in state["instances"].values():
                entry.pop("missing_since", None)
                entry.pop("last_observed", None)
            state.update(status="error", error_type=type(exc).__name__)
            write_state(path, state)
            return state
        state.pop("error_type", None)
        repairs = 0
        # Oldest attempted first: a repeatedly broken first instance cannot starve others.
        ordered = sorted(indices, key=lambda i: state["instances"].get(str(i), {}).get("last_attempt", 0))
        for index in ordered:
            key, network = str(index), f"LdNatNetwork{index}"
            previous = state["instances"].get(key, {})
            entry = {k: previous[k] for k in ("last_attempt",) if k in previous}
            state["instances"][key] = entry
            try:
                if f"leidian{index}" not in running:
                    entry["status"] = "stopped"
                elif owned_processes(processes, host.directory, network, "nat"):
                    entry["status"] = "nat_present"
                else:
                    # A normal startup gets a full observation interval before any action.
                    validate_vm(host.vm_info(index), index)
                    owned_processes(processes, host.directory, network, "dhcp")
                    last = previous.get("last_observed", now)
                    since = previous.get("missing_since", now)
                    consecutive = (0 <= now - last <= MAX_OBSERVATION_SECONDS and now >= since)
                    entry.update(status="observing_missing_nat", last_observed=now,
                        missing_since=since if consecutive else now)
                    if now - entry["missing_since"] >= MIN_OBSERVATION_SECONDS:
                        attempt = previous.get("last_attempt")
                        if attempt is not None and now < attempt:
                            # Recover conservatively after a backward clock step.
                            entry.update(last_attempt=now, status="cooldown")
                        elif attempt is not None and now - attempt < REPAIR_COOLDOWN_SECONDS:
                            entry["status"] = "cooldown"
                        elif repairs >= MAX_REPAIRS_PER_CYCLE:
                            entry["status"] = "deferred"
                        else:
                            entry.update(last_attempt=now, status="repair_started")
                            state["events"] = (state["events"] + [{"at": now, "instance": index,
                                "action": "repair_started"}])[-50:]
                            state["status"] = "repairing"
                            write_state(path, state)  # Failure here must prevent host mutation.
                            state["status"] = "ok"
                            repairs += 1
                            result = recover(host, index, repair=True)
                            entry.update(status="nat_restored", action=result["action"])
                            entry.pop("missing_since", None)
                            entry.pop("last_observed", None)
                            state["events"] = (state["events"] + [{"at": now, "instance": index,
                                "action": result["action"]}])[-50:]
            except ERRORS as exc:
                entry.update(status="error", error_type=type(exc).__name__)
                entry.pop("missing_since", None)
                entry.pop("last_observed", None)
                state["events"] = (state["events"] + [{"at": now, "instance": index,
                    "action": "error", "error_type": type(exc).__name__}])[-50:]
        state["status"] = "ok" if all(entry["status"] in ("stopped", "nat_present", "nat_restored")
            for entry in state["instances"].values()) else "degraded"
        write_state(path, state)
        return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--check-config", action="store_true", help="Validate and inspect only; no state write or repair")
    args = parser.parse_args()
    try:
        if args.config.stat().st_size > 16_384:
            raise ValueError("Configuration exceeds size limit")
        config = validate_config(json.loads(args.config.read_text(encoding="utf-8-sig")))
        if args.config.resolve() == Path(config["state_path"]).resolve():
            raise ValueError("State must not overwrite configuration")
        host = WindowsHost(Path(config["vboxmanage"]))
        if args.check_config:
            load_state(Path(config["state_path"]), {"directory": ntpath.normcase(host.directory),
                "indices": sorted(config["indices"])})
            host.running_vms()
            host.processes()
            print(json.dumps({"status": "config_valid", "indices": config["indices"], "read_only": True}))
            return
        result = run_cycle(host, config["indices"], Path(config["state_path"]))
        print(json.dumps(result))
        raise SystemExit(0 if result["status"] == "ok" else 2)
    except RecoveryBusy:
        print(json.dumps({"status": "busy", "mutation": False}))
        raise SystemExit(3) from None
    except ERRORS as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
