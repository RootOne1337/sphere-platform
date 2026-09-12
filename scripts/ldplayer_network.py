"""Inspect or repair one running LDPlayer's missing NAT service on Windows.

Read-only by default. --repair restarts only the selected network's orphan DHCP
process when NAT is absent, then starts the existing NAT network. No VM restart,
port forwarding, firewall changes, APK data reset, or other network is involved.
"""

from __future__ import annotations

import argparse
import json
import ntpath
import os
import re
import subprocess
import time
from pathlib import Path


class NetworkRecoveryError(RuntimeError):
    pass


def owned_processes(processes: list[dict], directory: str, network: str, kind: str) -> list[dict]:
    executable = "VBoxNetNAT.exe" if kind == "nat" else "VBoxNetDHCP.exe"
    flag = "--network" if kind == "nat" else "--comment"
    expected = ntpath.normcase(ntpath.join(directory, executable))
    pattern = re.compile(r"(?:^|\s)" + flag + r'\s+(?:"' + re.escape(network)
        + r'"|' + re.escape(network) + r")(?=\s|$)")
    candidates = [p for p in processes if p.get("Name", "").lower() == executable.lower()
        and pattern.search(p.get("CommandLine") or "")]
    if any(ntpath.normcase(p.get("ExecutablePath") or "") != expected for p in candidates):
        raise NetworkRecoveryError("Selected network has an unverified process executable")
    if len(candidates) > 1:
        raise NetworkRecoveryError("Ambiguous processes for the selected network")
    return candidates


def validate_vm(output: str, index: int) -> str:
    values = dict(re.findall(r'^([A-Za-z0-9_-]+)="([^"\r\n]*)"$', output, re.MULTILINE))
    network = f"LdNatNetwork{index}"
    if (values.get("name") != f"leidian{index}" or values.get("VMState") != "running"
            or values.get("nic1") != "natnetwork" or values.get("nat-network1") != network
            or values.get("cableconnected1") != "on"):
        raise NetworkRecoveryError("Expected a running selected VM with its dedicated NAT network")
    return network


def recover(host, index: int, *, repair: bool = False) -> dict:
    if not 0 <= index <= 4095:
        raise ValueError("Invalid LDPlayer index")
    network = validate_vm(host.vm_info(index), index)
    processes = host.processes()
    nat = owned_processes(processes, host.directory, network, "nat")
    dhcp = owned_processes(processes, host.directory, network, "dhcp")
    result = {"instance": index, "network": network, "nat_running": bool(nat),
        "dhcp_running": bool(dhcp), "action": "unchanged" if nat else "missing_nat",
        "internet_verified": False, "apk_connection_verified": False}
    if nat or not repair:
        return result
    # Revalidate immediately before any mutation, including races with emulator
    # startup. Never stop a DHCP process when NAT recovered by itself meanwhile.
    validate_vm(host.vm_info(index), index)
    fresh = host.processes()
    if owned_processes(fresh, host.directory, network, "nat"):
        return {**result, "nat_running": True, "action": "recovered_concurrently"}
    current_dhcp = owned_processes(fresh, host.directory, network, "dhcp")
    if current_dhcp != dhcp:
        raise NetworkRecoveryError("DHCP identity changed; retry inspection")
    if dhcp:
        host.stop_verified_dhcp(dhcp[0], network)
    host.start_network(network)
    for _ in range(20):
        validate_vm(host.vm_info(index), index)
        current = host.processes()
        if owned_processes(current, host.directory, network, "nat"):
            return {**result, "nat_running": True,
                "dhcp_running": bool(owned_processes(current, host.directory, network, "dhcp")),
                "action": "started_existing_network"}
        host.sleep(0.25)
    raise NetworkRecoveryError("NAT process did not appear; recovery is not confirmed")


class WindowsHost:
    def __init__(self, vboxmanage: Path):
        if os.name != "nt":
            raise NetworkRecoveryError("This adapter is for Windows LDPlayer")
        self.vboxmanage = vboxmanage.resolve(strict=True)
        if self.vboxmanage.name.lower() != "vboxmanage.exe":
            raise ValueError("Expected the LDPlayer VBoxManage.exe")
        self.directory = str(self.vboxmanage.parent)

    @staticmethod
    def call(args: list[str]) -> str:
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise NetworkRecoveryError(f"Scoped command failed with exit code {result.returncode}")
        return result.stdout

    def powershell(self, code: str) -> str:
        return self.call(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new(); " + code])

    def vm_info(self, index: int) -> str:
        return self.call([str(self.vboxmanage), "showvminfo", f"leidian{index}", "--machinereadable"])

    def processes(self) -> list[dict]:
        raw = self.powershell("@(@(Get-CimInstance Win32_Process -Filter \"Name='VBoxNetNAT.exe' OR Name='VBoxNetDHCP.exe'\") | "
            "Select-Object Name,ProcessId,ExecutablePath,CommandLine,@{n='Created';e={$_.CreationDate.ToUniversalTime().ToString('o')}}) | ConvertTo-Json -Compress")
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else [value]

    def stop_verified_dhcp(self, process: dict, network: str) -> None:
        # Check creation time (PID reuse), executable, command line and absence
        # of NAT in the same PowerShell call that performs the narrowly scoped stop.
        def literal(value):
            return "'" + str(value).replace("'", "''") + "'"
        process_id = int(process["ProcessId"])
        if process_id <= 0:
            raise ValueError("Invalid process ID")
        self.powershell(
            "$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(process_id) + "'; "
            "if (-not $p -or $p.Name -ne 'VBoxNetDHCP.exe' -or $p.ExecutablePath -ne "
            + literal(process["ExecutablePath"]) + " -or $p.CommandLine -ne " + literal(process["CommandLine"])
            + " -or $p.CreationDate.ToUniversalTime().ToString('o') -ne " + literal(process["Created"])
            + ") { throw 'DHCP identity changed' }; "
            "$nat=@(Get-CimInstance Win32_Process -Filter \"Name='VBoxNetNAT.exe'\" | Where-Object { $_.CommandLine -match "
            + literal(r'(?:^|\s)--network\s+(?:"' + network + r'"|' + network + r')(?=\s|$)')
            + " }); if ($nat.Count) { throw 'NAT recovered concurrently' }; Stop-Process -Id " + str(process_id) + " -Force"
        )

    def start_network(self, network: str) -> None:
        self.call([str(self.vboxmanage), "natnetwork", "start", "--netname", network])

    sleep = staticmethod(time.sleep)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=int, required=True)
    parser.add_argument("--vboxmanage", type=Path, required=True)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    try:
        result = recover(WindowsHost(args.vboxmanage), args.index, repair=args.repair)
    except (NetworkRecoveryError, ValueError, OSError) as exc:
        print(json.dumps({"status": "error", "error_type": type(exc).__name__, "reason": str(exc)}))
        raise SystemExit(1) from None
    print(json.dumps(result))
    raise SystemExit(0 if result["nat_running"] else 2)


if __name__ == "__main__":
    main()
