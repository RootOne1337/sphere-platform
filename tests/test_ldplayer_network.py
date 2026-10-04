"""NAT recovery is scoped to one explicit running VM; all host effects are recorded."""

from contextlib import nullcontext
from pathlib import Path

import pytest

from scripts.ldplayer_network import NetworkRecoveryError, WindowsHost, owned_processes, recover


def process(index, kind, pid=101, directory=r"C:\Program Files\ldplayer9box"):
    name = "VBoxNetNAT.exe" if kind == "nat" else "VBoxNetDHCP.exe"
    flag = "--network" if kind == "nat" else "--comment"
    return {"Name": name, "ProcessId": pid, "Created": "2026-09-12T00:00:00Z",
        "ExecutablePath": directory + "\\" + name,
        "CommandLine": f'"{directory}\\{name}" {flag} LdNatNetwork{index} --other value'}


class Host:
    directory = r"C:\Program Files\ldplayer9box"

    def __init__(self, *, nat=False, dhcp=True):
        self.entries = [process(0, "nat", 50), process(0, "dhcp", 51), process(10, "dhcp", 52)]
        self.entries += ([process(1, "dhcp")] if dhcp else []) + ([process(1, "nat", 102)] if nat else [])
        self.changes = []
        self.state = "running"
        self.network = "LdNatNetwork1"
        self.start_succeeds = True
        self.info_calls = 0

    def vm_info(self, index):
        self.info_calls += 1
        return (f'name="leidian{index}"\nVMState="{self.state}"\nnic1="natnetwork"\n'
            f'nat-network1="{self.network}"\ncableconnected1="on"\n')

    def repair_lock(self):
        return nullcontext()

    def assert_dedicated(self, index, network):
        pass

    def processes(self):
        return list(self.entries)

    def stop_verified_dhcp(self, entry, network):
        self.changes.append(("stop", entry["ProcessId"], network))
        self.entries.remove(entry)

    def start_network(self, network):
        self.changes.append(("start", network))
        if self.start_succeeds:
            self.entries.extend([process(1, "nat", 103), process(1, "dhcp", 104)])

    def sleep(self, delay):
        pass


@pytest.mark.parametrize("repair", [False, True])
def test_healthy_network_is_never_restarted(repair):
    host = Host(nat=True)
    assert recover(host, 1, repair=repair)["action"] == "unchanged"
    assert host.changes == []


def test_read_only_reports_missing_nat_without_touching_orphan_dhcp():
    host = Host()
    assert recover(host, 1)["action"] == "missing_nat"
    assert host.changes == []


@pytest.mark.parametrize("dhcp", [True, False])
def test_repair_changes_only_selected_network(dhcp):
    host = Host(dhcp=dhcp)
    other = host.entries[:3]
    result = recover(host, 1, repair=True)
    assert result["action"] == "started_existing_network" and result["nat_running"]
    assert not result["internet_verified"] and not result["apk_connection_verified"]
    assert host.entries[:3] == other
    assert host.changes == ([("stop", 101, "LdNatNetwork1")] if dhcp else []) + [("start", "LdNatNetwork1")]


@pytest.mark.parametrize("state,network", [("poweroff", "LdNatNetwork1"), ("running", "LdNatNetwork0")])
def test_stopped_or_shared_network_vm_is_rejected(state, network):
    host = Host()
    host.state, host.network = state, network
    with pytest.raises(NetworkRecoveryError):
        recover(host, 1, repair=True)
    assert not host.changes


@pytest.mark.parametrize("ambiguous", [False, True])
def test_wrong_binary_or_multiple_owners_are_rejected(ambiguous):
    host = Host()
    host.entries.append(process(1, "dhcp", 200, directory=host.directory if ambiguous else r"C:\Unrelated"))
    with pytest.raises(NetworkRecoveryError):
        recover(host, 1, repair=True)
    assert not host.changes


def test_failed_start_is_not_reported_as_restored():
    host = Host()
    host.start_succeeds = False
    with pytest.raises(NetworkRecoveryError, match="did not appear"):
        recover(host, 1, repair=True)


def test_concurrent_nat_recovery_prevents_dhcp_stop():
    host = Host()
    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        return host.entries + ([process(1, "nat", 202)] if calls == 2 else [])
    host.processes = snapshot
    assert recover(host, 1, repair=True)["action"] == "recovered_concurrently"
    assert not host.changes


def test_reused_dhcp_pid_prevents_mutation():
    host = Host()
    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        values = [dict(entry) for entry in host.entries]
        if calls == 2:
            values[-1]["Created"] = "2026-09-13T00:00:00Z"
        return values
    host.processes = snapshot
    with pytest.raises(NetworkRecoveryError, match="identity changed"):
        recover(host, 1, repair=True)
    assert not host.changes


def test_quoted_network_name_and_index_boundary():
    entry = process(1, "nat")
    entry["CommandLine"] = entry["CommandLine"].replace("LdNatNetwork1", '"LdNatNetwork1"')
    assert owned_processes([entry, process(10, "nat")], Host.directory, "LdNatNetwork1", "nat") == [entry]


@pytest.mark.parametrize("index", [-1, 4096])
def test_invalid_index_is_rejected_before_host_inspection(index):
    host = Host()
    with pytest.raises(ValueError):
        recover(host, index, repair=True)
    assert not host.info_calls and not host.changes


@pytest.mark.parametrize("raw", ['null', '[{}]', '[{"Name":"VBoxNetNAT.exe"}]'])
def test_native_adapter_rejects_incomplete_process_identity(raw):
    host = object.__new__(WindowsHost)
    host.powershell = lambda code: raw
    with pytest.raises(NetworkRecoveryError, match="identities"):
        host.processes()


@pytest.mark.parametrize("raw", ['unexpected output', '"vm" {bad-id}',
    '"vm" {20160302-aaaa-aaaa-0eee-000000000000}\n"vm" {20160302-aaaa-aaaa-0eee-000000000001}'])
def test_native_adapter_rejects_ambiguous_inventory(raw):
    host = object.__new__(WindowsHost)
    host.vboxmanage = Path("VBoxManage.exe")
    host.call = lambda args: raw
    with pytest.raises(NetworkRecoveryError):
        host.running_vms()


def test_native_adapter_rejects_other_vm_sharing_secondary_nic():
    host = object.__new__(WindowsHost)
    host.vboxmanage = Path("VBoxManage.exe")
    host.vm_info = Host().vm_info
    host.running_vms = lambda: {"leidian1": "selected", "custom-vm": "other"}
    host.call = lambda args: 'name="custom-vm"\nnat-network2="LdNatNetwork1"\n'
    with pytest.raises(NetworkRecoveryError, match="shared"):
        host.assert_dedicated(1, "LdNatNetwork1")


def test_native_adapter_checks_creation_time_in_same_dhcp_stop_command():
    host = object.__new__(WindowsHost)
    commands = []
    host.powershell = commands.append
    host.stop_verified_dhcp(process(1, "dhcp"), "LdNatNetwork1")
    command = commands[0]
    assert "CreationDate.ToUniversalTime()" in command and "ExecutablePath -ne" in command
    assert "CommandLine -ne" in command and "if ($nat.Count)" in command
    assert command.endswith("Stop-Process -Id 101 -Force")
